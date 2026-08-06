from rp_core.errors import CorruptFileError, InputError


class RpPptxError(InputError):
    pass


class MissingFileError(RpPptxError, FileNotFoundError):
    pass


class InvalidPptxError(CorruptFileError):
    pass


class UnsupportedFeatureError(CorruptFileError):
    pass
