import warnings
from bs4 import XMLParsedAsHTMLWarning

from .importer import process_epub

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)