# Copyright 2024 Liu Siyao
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import List, Optional, Union

from pydantic import BaseModel


class ConversionConfig(BaseModel):
    """Configuration for PowerPoint to Markdown conversion."""

    pptx_path: Path
    """Path to the pptx file to be converted"""

    output_path: Path
    """Path of the output file"""

    image_dir: Optional[Path]
    """Where to put images extracted"""

    title_path: Optional[Path] = None
    """Path to the custom title list file"""

    image_width: Optional[int] = None
    """Maximum image width in px"""

    disable_image: bool = False
    """Disable image extraction"""

    disable_wmf: bool = False
    """Keep wmf formatted image untouched (avoid exceptions under linux)"""

    disable_color: bool = False
    """Do not add color HTML tags"""

    disable_escaping: bool = False
    """Do not attempt to escape special characters"""

    disable_notes: bool = False
    """Do not add presenter notes"""

    enable_slides: bool = False
    """Deliniate slides with `\n---\n`"""

    is_wiki: bool = False
    """Generate output as wikitext (TiddlyWiki)"""

    is_mdk: bool = False
    """Generate output as madoko markdown"""

    is_qmd: bool = False
    """Generate output as quarto markdown presentation"""

    min_block_size: int = 15
    """The minimum character number of a text block to be converted"""

    page: Optional[int] = None
    """Only convert the specified page"""

    custom_titles: dict[str, int] = {}
    """Mapping of custom titles to their heading levels"""

    try_multi_column: bool = False
    """Try to detect multi-column slides"""

    keep_similar_titles: bool = False
    """Keep similar titles (allow for repeated slide titles - One or more - Add (cont.) to the title)"""


class ElementType(str, Enum):
    Title = "Title"
    ListItem = "ListItem"
    Paragraph = "Paragraph"
    Image = "Image"
    Table = "Table"


class TextStyle(BaseModel):
    is_accent: bool = False
    is_strong: bool = False
    color_rgb: Optional[tuple[int, int, int]] = None
    hyperlink: Optional[str] = None


class TextRun(BaseModel):
    text: str
    style: TextStyle


class Position(BaseModel):
    left: float
    top: float
    width: float
    height: float


class BaseElement(BaseModel):
    type: ElementType
    position: Optional[Position] = None
    style: Optional[TextStyle] = None


class TitleElement(BaseElement):
    type: ElementType = ElementType.Title
    content: str
    level: int


class ListItemElement(BaseElement):
    type: ElementType = ElementType.ListItem
    content: List[TextRun]
    level: int = 1


class ParagraphElement(BaseElement):
    type: ElementType = ElementType.Paragraph
    content: List[TextRun]


class ImageElement(BaseElement):
    type: ElementType = ElementType.Image
    path: str
    width: Optional[int] = None
    original_ext: str = ""  # For tracking original file extension (e.g. wmf)
    alt_text: str = ""  # For accessibility


class TableElement(BaseElement):
    type: ElementType = ElementType.Table
    content: List[List[List[TextRun]]]  # rows -> cols -> rich text


SlideElement = Union[TitleElement, ListItemElement, ParagraphElement, ImageElement, TableElement]


class SlideType(str, Enum):
    MultiColumn = "MultiColumn"
    General = "General"


class MultiColumnSlide(BaseModel):
    type: SlideType = SlideType.MultiColumn
    preface: List[SlideElement]
    columns: List[SlideElement]
    notes: List[str] = []


class GeneralSlide(BaseModel):
    type: SlideType = SlideType.General
    elements: List[SlideElement]
    notes: List[str] = []


Slide = Union[GeneralSlide, MultiColumnSlide]


class ParsedPresentation(BaseModel):
    slides: List[Slide]
