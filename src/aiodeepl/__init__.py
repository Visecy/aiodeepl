from deepl import *  # noqa: F403

from .translator import Translator
from .version import VERSION as __version__


__author__ = "Visecy <visecy@visecy.org>"


__all__ = [
    "__version__",
    "__author__",
    "DocumentHandle",
    "DocumentStatus",
    "Formality",
    "GlossaryInfo",
    "Language",
    "SplitSentences",
    "TextResult",
    "Translator",
    "Usage",
    "http_client",
    "AuthorizationException",
    "ConnectionException",
    "DeepLException",
    "DocumentNotReadyException",
    "DocumentTranslationException",
    "GlossaryNotFoundException",
    "TooManyRequestsException",
    "QuotaExceededException",
    "auth_key_is_free_account",
    "convert_tsv_to_dict",
    "convert_dict_to_tsv",
    "validate_glossary_term",
]

