from typing import Any, Union

class ConverterInput:
    """
    Wrapper for inputs to converter functions.
    """
    def __init__(
        self,
        input_type: str = "filepath",
        filepath: Union[str, None] = None,
        file_object: Union[Any, None] = None,
    ):
        if input_type not in ["filepath", "object"]:
            raise ValueError(f"Invalid converter input type: {input_type}")
        
        self.input_type = input_type
        self.filepath = filepath
        self.file_object = file_object