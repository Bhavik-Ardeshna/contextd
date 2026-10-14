"""Text converters for converting files and URLs to markdown."""

from .code_converter import CodeConverter
from .html_converter import HtmlConverter
from .mistral_converter import MistralConverter
from .txt_converter import TxtConverter
from .web_converter import WebConverter
from .xlsx_converter import XlsxConverter

# Singleton instances
mistral_converter = MistralConverter()
html_converter = HtmlConverter()
xlsx_converter = XlsxConverter()  # Local openpyxl extraction (not Mistral)
txt_converter = TxtConverter()
code_converter = CodeConverter()
web_converter = WebConverter()  # URL fetching and HTML to markdown

__all__ = [
    "mistral_converter",
    "html_converter",
    "txt_converter",
    "xlsx_converter",
    "code_converter",
    "web_converter",
]
