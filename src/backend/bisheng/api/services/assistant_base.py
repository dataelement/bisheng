import os

from tiktoken.load import load_tiktoken_bpe
from tiktoken.core import Encoding as TikTokenEncoding


class AssistantUtils:
    # 忽略助手配置已从系统配置中移除，暂不需要此类的方法

    @staticmethod
    def cl100k_base() -> TikTokenEncoding:
        ENDOFTEXT = "<|endoftext|>"
        FIM_PREFIX = "<|fim_prefix|>"
        FIM_MIDDLE = "<|fim_middle|>"
        FIM_SUFFIX = "<|fim_suffix|>"
        ENDOFPROMPT = "<|endofprompt|>"

        tiktoken_file = os.path.join(os.path.dirname(__file__), "tiktoken_file/cl100k_base.tiktoken")

        mergeable_ranks = load_tiktoken_bpe(
            # "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
            tiktoken_file,
            expected_hash="223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
        )
        special_tokens = {
            ENDOFTEXT: 100257,
            FIM_PREFIX: 100258,
            FIM_MIDDLE: 100259,
            FIM_SUFFIX: 100260,
            ENDOFPROMPT: 100276,
        }
        return TikTokenEncoding(**{
            "name": "cl100k_base",
            "pat_str": r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s""",
            "mergeable_ranks": mergeable_ranks,
            "special_tokens": special_tokens,
        })
