import puremagic
import mimetypes
import zipfile
import os
from dataclasses import dataclass, asdict
from typing import Optional, BinaryIO, List, Union

# Mimetype substitutions table
MIMETYPE_SUBSTITUTIONS = {
    "application/excel": "application/vnd.ms-excel",
    "application/mspowerpoint": "application/vnd.ms-powerpoint",
}


@dataclass(kw_only=True, frozen=True)
class StreamInfo:
    """The StreamInfo class is used to store information about a file stream.
    All fields can be None, and will depend on how the stream was opened.
    """

    mimetype: Optional[str] = None
    extension: Optional[str] = None
    charset: Optional[str] = None
    filename: Optional[
        str
    ] = None  # From local path, url, or Content-Disposition header
    local_path: Optional[str] = None  # If read from disk
    url: Optional[str] = None  # If read from url

    def copy_and_update(self, *args, **kwargs):
        """Copy the StreamInfo object and update it with the given StreamInfo
        instance and/or other keyword arguments."""
        new_info = asdict(self)

        for si in args:
            assert isinstance(si, StreamInfo)
            new_info.update({k: v for k, v in asdict(si).items() if v is not None})

        if len(kwargs) > 0:
            new_info.update(kwargs)

        return StreamInfo(**new_info)


# Behavior subject to change.
# Do not rely on this outside of this module.
def _guess_stream_info_from_stream(
    file_stream: BinaryIO,
    *,
    filename_hint: Optional[str] = None,
) -> List[StreamInfo]:
    """
    Guess StreamInfo properties (mostly mimetype and extension) from a stream.

    Args:
    - stream: The stream to guess the StreamInfo from.
    - filename_hint [Optional]: A filename hint to help with the guessing (may be a placeholder, and not actually be the file name)

    Returns a list of StreamInfo objects in order of confidence.
    """
    guesses: List[StreamInfo] = []

    # Add a guess purely based on the filename hint
    if filename_hint:
        try:
            # Requires Python 3.13+
            mimetype, _ = mimetypes.guess_file_type(filename_hint)  # type: ignore
        except AttributeError:
            mimetype, _ = mimetypes.guess_type(filename_hint)

        if mimetype:
            guesses.append(
                StreamInfo(
                    mimetype=mimetype, extension=os.path.splitext(filename_hint)[1]
                )
            )

    # If it looks like a zip use _guess_stream_info_from_zip rather than puremagic
    cur_pos = file_stream.tell()
    try:
        header = file_stream.read(4)
        file_stream.seek(cur_pos)
        if header == b"PK\x03\x04":
            zip_guess = _guess_stream_info_from_zip(file_stream)
            if zip_guess:
                guesses.append(zip_guess)
                return guesses
    finally:
        file_stream.seek(cur_pos)

    # Fall back to using puremagic
    def _puremagic(
        file_stream, filename_hint
    ) -> List[puremagic.main.PureMagicWithConfidence]:
        """Wrap guesses to handle exceptions."""
        try:
            return puremagic.magic_stream(file_stream, filename=filename_hint)
        except puremagic.main.PureError as e:
            return []

    cur_pos = file_stream.tell()
    type_guesses = _puremagic(file_stream, filename_hint=filename_hint)
    if len(type_guesses) == 0:
        # Fix for: https://github.com/microsoft/markitdown/issues/222
        # If there are no guesses, then try again after trimming leading ASCII whitespaces.
        # ASCII whitespace characters are those byte values in the sequence b' \t\n\r\x0b\f'
        # (space, tab, newline, carriage return, vertical tab, form feed).

        # Eat all the leading whitespace
        file_stream.seek(cur_pos)
        while True:
            char = file_stream.read(1)
            if not char:  # End of file
                break
            if not char.isspace():
                file_stream.seek(file_stream.tell() - 1)
                break

        # Try again
        type_guesses = _puremagic(file_stream, filename_hint=filename_hint)
    file_stream.seek(cur_pos)

    # Convert and return the guesses
    for guess in type_guesses:
        kwargs: dict[str, str] = {}
        if guess.extension:
            kwargs["extension"] = guess.extension
        if guess.mime_type:
            kwargs["mimetype"] = MIMETYPE_SUBSTITUTIONS.get(
                guess.mime_type, guess.mime_type
            )
        if len(kwargs) > 0:
            # We don't add the filename_hint, because sometimes it's just a placeholder,
            # and, in any case, doesn't add new information.
            guesses.append(StreamInfo(**kwargs))

    return guesses


def _guess_stream_info_from_zip(file_stream: BinaryIO) -> Union[None, StreamInfo]:
    """
    Guess StreamInfo properties (mostly mimetype and extension) from a zip stream.

    Args:
    - stream: The stream to guess the StreamInfo from.

    Returns the single best guess, or None if no guess could be made.
    """

    cur_pos = file_stream.tell()
    try:
        with zipfile.ZipFile(file_stream) as z:
            table_of_contents = z.namelist()

            # OpenPackageFormat (OPF) file
            if "[Content_Types].xml" in table_of_contents:
                # Word file
                if "word/document.xml" in table_of_contents:
                    return StreamInfo(
                        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        extension=".docx",
                    )

                # Excel file
                if "xl/workbook.xml" in table_of_contents:
                    return StreamInfo(
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        extension=".xlsx",
                    )

                # PowerPoint file
                if "ppt/presentation.xml" in table_of_contents:
                    return StreamInfo(
                        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        extension=".pptx",
                    )

                # Visio file
                if "visio/document.xml" in table_of_contents:
                    return StreamInfo(
                        mimetype="application/vnd.ms-visio.drawing",
                        extension=".vsd",
                    )

                # XPS file
                if "FixedDocSeq.fdseq" in table_of_contents:
                    return StreamInfo(
                        mimetype="application/vnd.ms-xpsdocument",
                        extension=".xps",
                    )

            # EPUB, or similar
            if "mimetype" in table_of_contents:
                _mimetype = z.read("mimetype").decode("ascii").strip()
                _extension = mimetypes.guess_extension(_mimetype)
                return StreamInfo(mimetype=_mimetype, extension=_extension)

            # JAR
            if "META-INF/MANIFEST.MF" in table_of_contents:
                return StreamInfo(mimetype="application/java-archive", extension=".jar")

            # If we made it this far, we couldn't identify the file
            return StreamInfo(mimetype="application/zip", extension=".zip")

    except zipfile.BadZipFile:
        return None
    finally:
        file_stream.seek(cur_pos)
