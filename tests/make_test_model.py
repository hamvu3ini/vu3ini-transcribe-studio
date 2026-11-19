"""Build a tiny random-weight Whisper model in CTranslate2 format, with a matching
tokenizer.json, so the real faster-whisper pipeline can be exercised offline in tests.
Its output is meaningless text; it only proves the plumbing works."""
import json, os, sys
import numpy as np
from ctranslate2 import specs

LANGS = ("en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da hu ta no th ur hr bg "
         "lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af "
         "oc ka be tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue").split()

def vocab():
    base = [bytes([b]).decode("latin-1") for b in range(256)]
    toks = base + [f"\u0120w{i}" for i in range(50257 - 256)]
    toks += ["<|endoftext|>", "<|startoftranscript|>"] + [f"<|{l}|>" for l in LANGS]
    toks += ["<|translate|>", "<|transcribe|>", "<|startoflm|>", "<|startofprev|>", "<|nocaptions|>", "<|notimestamps|>"]
    toks += [f"<|{i*0.02:.2f}|>" for i in range(1501)]
    assert len(toks) == 51866, len(toks)
    return toks

def main(out):
    rng = np.random.default_rng(0)
    d, ff, mels, L, H = 64, 128, 80, 2, 2
    toks = vocab(); V = len(toks)
    spec = specs.WhisperSpec(L, H, L, H)
    r = lambda *s: (rng.standard_normal(s) * 0.05).astype(np.float32)
    z = lambda *s: np.zeros(s, np.float32); o = lambda *s: np.ones(s, np.float32)
    def ln(x): x.gamma = o(d); x.beta = z(d)
    def lin(x, a, b): x.weight = r(a, b); x.bias = z(a)
    def ffn(x): ln(x.layer_norm); lin(x.linear_0, ff, d); lin(x.linear_1, d, ff)
    def selfatt(x): ln(x.layer_norm); lin(x.linear[0], 3 * d, d); lin(x.linear[1], d, d)
    e = spec.encoder
    e.conv1.weight = r(d, mels, 3); e.conv1.bias = z(d)
    e.conv2.weight = r(d, d, 3); e.conv2.bias = z(d)
    e.position_encodings.encodings = r(1500, d)
    for lay in e.layer: selfatt(lay.self_attention); ffn(lay.ffn)
    ln(e.layer_norm)
    dc = spec.decoder
    dc.embeddings.weight = r(V, d)
    dc.position_encodings.encodings = r(448, d)
    for lay in dc.layer:
        selfatt(lay.self_attention)
        a = lay.attention; ln(a.layer_norm); lin(a.linear[0], d, d); lin(a.linear[1], 2 * d, d); lin(a.linear[2], d, d)
        ffn(lay.ffn)
    # Make the decoder deterministic: a constant final hidden state that favours a
    # short cycle of ordinary word tokens, so tests always get some text back.
    dc.layer_norm.gamma = z(d); u = np.zeros(d, np.float32); u[0] = 1.0
    dc.layer_norm.beta = u * 4
    emb = dc.embeddings.weight
    for k, t in enumerate((1000, 1001, 1002)):
        emb[t] = u * (12 - k)
    dc.projection.weight = emb
    spec.config.alignment_heads = [[1, 0], [1, 1]]
    spec.config.lang_ids = [toks.index(f"<|{l}|>") for l in LANGS]
    spec.config.suppress_ids = []
    spec.config.suppress_ids_begin = [220, 50257]
    reg_all = [_bytes_to_unicode()[b] for b in range(256)] + toks[256:]
    spec.register_vocabulary(reg_all)
    os.makedirs(out, exist_ok=True)
    spec.validate(); spec.optimize(quantization="float32")
    spec.save(out)
    # minimal byte-level tokenizer.json understood by the `tokenizers` library
    vocab_map = {}
    from tokenizers import Tokenizer, models, pre_tokenizers, decoders
    bl = pre_tokenizers.ByteLevel.alphabet()
    # map byte tokens to ByteLevel alphabet chars so decode works
    from tokenizers.pre_tokenizers import ByteLevel
    byte_chars = _bytes_to_unicode()
    reg = [byte_chars[b] for b in range(256)] + toks[256:50257]
    vocab_map = {t: i for i, t in enumerate(reg)}
    tk = Tokenizer(models.BPE(vocab=vocab_map, merges=[]))
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tk.decoder = decoders.ByteLevel()
    from tokenizers import AddedToken
    tk.add_special_tokens([AddedToken(t, special=True) for t in toks[50257:]])
    tk.save(os.path.join(out, "tokenizer.json"))
    json.dump({"test_model": True}, open(os.path.join(out, "vt_test_model.json"), "w"))

def _bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]; n = 0
    for b in range(256):
        if b not in bs: bs.append(b); cs.append(256 + n); n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}

if __name__ == "__main__":
    main(sys.argv[1])
