"""The part of lizard's API these hooks use (lizard ships no types)."""

class FunctionInfo:
    name: str
    long_name: str
    start_line: int
    cyclomatic_complexity: int

class FileInformation:
    filename: str
    function_list: list[FunctionInfo]

def analyze_file(filename: str) -> FileInformation: ...
def get_reader_for(filename: str) -> type | None: ...
