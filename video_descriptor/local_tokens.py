"""Count text with the selected Ollama model's vocabulary, without inference.

Only known byte BPE pre-tokenizers are reconstructed. Unknown formats retain the
conservative byte bound. No Hugging Face access, model loading or downloads.
"""

import requests

QWEN = (r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}"
        r"| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+")
QWEN35 = QWEN.replace(r"?\p{L}+", r"?[\p{L}\p{M}]+").replace(
    r"[^\s\p{L}\p{N}]", r"[^\s\p{L}\p{M}\p{N}]")
PATTERNS = {'qwen2': QWEN, 'deepseek-r1-qwen': QWEN, 'qwen35': QWEN35}


def byte_bound(text):
    return len(text.encode('utf-8')) + 256


class TokenCounter:
    def __init__(self, tokenizer=None):
        self.tokenizer = tokenizer
        self.mode = 'model-vocabulary' if tokenizer is not None else 'byte-bound'

    def __call__(self, text):
        if self.tokenizer is None:
            return byte_bound(text)
        # Raw text tokens are exact; reserve framing separately rather than
        # pretending to implement Ollama's model-specific Go chat templates.
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids) + 256


def from_metadata(info):
    pattern = PATTERNS.get(info.get('tokenizer.ggml.pre'))
    tokens = info.get('tokenizer.ggml.tokens')
    merges = info.get('tokenizer.ggml.merges')
    if info.get('tokenizer.ggml.model') != 'gpt2' or not pattern or not tokens or not merges:
        return TokenCounter()
    if any(info.get('tokenizer.ggml.normalizer.' + option)
           for option in ('lowercase', 'strip_accents')):
        return TokenCounter()
    try:
        from tokenizers import Regex, Tokenizer, models, normalizers, pre_tokenizers
        vocab = {token: index for index, token in enumerate(tokens)}
        if len(vocab) != len(tokens) or not set(pre_tokenizers.ByteLevel.alphabet()) <= vocab.keys():
            return TokenCounter()
        tokenizer = Tokenizer(models.BPE(vocab, [tuple(pair.split(' ', 1)) for pair in merges]))
        if info.get('tokenizer.ggml.normalizer.nfc'):
            tokenizer.normalizer = normalizers.NFC()
        tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
            pre_tokenizers.Split(Regex(pattern), behavior='isolated'),
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ])
        # Control strings in a transcript remain ordinary data. Not registering
        # special tokens overcounts them safely rather than hiding their cost.
        return TokenCounter(tokenizer)
    except Exception:  # noqa: BLE001 — optional Rust tokenizer may raise a plain Exception.
        # The Rust constructor can raise a plain Exception for malformed vocab.
        # Do not expose metadata or make tokenization availability a job failure.
        return TokenCounter()


def load_counter(base_url, model):
    try:
        response = requests.post(base_url.rstrip('/') + '/api/show',
                                 json={'model': model, 'verbose': True}, timeout=(5, 30))
        try:
            response.raise_for_status()
            return from_metadata(response.json().get('model_info', {}))
        finally:
            response.close()
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return TokenCounter()
