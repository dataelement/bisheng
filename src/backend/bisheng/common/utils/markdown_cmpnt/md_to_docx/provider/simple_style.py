import docx

from docx.enum.style import WD_STYLE_TYPE


# Chinese Font Size Conversion pt THE METHOD
def _zihao_to_pt(chn_name: str):
    chn_name = chn_name.strip()
    pt_mapping = {
        "No. 1": 42,
        "Little Primary": 36,
        "No. 1": 26,
        "Little Yi": 24,
        "No. 2": 22,
        "Second": 18,
        "Number three": 16,
        "Little San": 15,
        "No. 4": 14,
        "Shikama": 12,
        "No. 5": 10.5,
        "Xiao Wu": 9,
        "No. 6": 7.5,
        "Little Six": 6.5,
        "No. 7": 5.5,
        "No. 8": 5,
    }
    if pt_mapping.get(chn_name):
        return pt_mapping[chn_name]
    else:
        print("[YAML ERROR]:", chn_name,
              "Not a canonical title.(In the Chinese context, the largest font size is'No. 1', the minimum is'No. 8')。")


class SimpleStyle:
    style_name: str
    base_style_name: str
    style_type: WD_STYLE_TYPE = WD_STYLE_TYPE.PARAGRAPH

    font_default: str = "Times New Roman"
    font_east_asia: str = "Song Ti"
    font_size: float = 14
    font_color: str = "000000"

    font_bold: bool = False
    font_italic: bool = False
    font_underline: bool = False
    font_strike: bool = False

    first_line_indent: int = 0
    line_spacing: int = 1
    space_before: int = 0
    space_after: int = 0

    def __init__(self,
                 style_name: str,  # Style name
                 base_style_name: str,  # Styles based on
                 conf: dict,  # Specific style data fromyamlDeserialized
                 style_type: docx.enum.style = WD_STYLE_TYPE.PARAGRAPH  # Is it a paragraph or a list or some other type
                 ):
        self.style_name = style_name
        self.base_style_name = base_style_name
        self.style_type = style_type

        try:
            self.font_default = conf["font"]["default"]
            self.font_east_asia = conf["font"]["east-asia"]

            if str(conf["font"]["size"]).isdigit():
                self.font_size = conf["font"]["size"]
            else:  # If the font size is given in Chinese, convert it
                self.font_size = _zihao_to_pt(conf["font"]["size"])
        except KeyError:
            print("[YAML ERROR]:", style_name,
                  "| Error occurred in setting font style. Set to:",
                  self.font_default, self.font_east_asia, str(self.font_size) + "pt")

        # Check when color is specified, do not specify default black
        if conf["font"].get("color") is not None:
            try:
                if type(conf["font"]["color"]) != str \
                        or len(conf["font"]["color"]) != 6:
                    raise TypeError
                # Try to convert to16binary number and whether it matchesRGBsize
                hex_num = int(conf["font"]["color"], 16)
                if 0 <= hex_num <= 0xFFFFFF:
                    self.font_color = str(conf["font"]["color"])
                else:
                    raise ValueError
            except ValueError:
                print("[YAML ERROR]:", style_name,
                      "| Value of color isn't a hex or out of [000000, FFFFFF].",
                      "Default to black(000000).")
            except TypeError:
                print("[YAML ERROR]:", style_name, "| Value of color must be string with 6 characters.",
                      "Default to black(000000).")

        # Bold, Italic, Underline, Strikeout
        if conf.get("font").get("extra"):
            # print(conf["font"]["extra"])
            self.font_bold = "bold" in (conf["font"]["extra"])
            self.font_italic = "italic" in list(conf["font"]["extra"])
            self.font_underline = "underline" in list(conf["font"]["extra"])
            self.font_strike = "strike" in list(conf["font"]["extra"])

        if conf.get("first-line-indent"):
            self.first_line_indent = conf["first-line-indent"]
        if conf.get("line-spacing"):
            self.line_spacing = conf["line-spacing"]
        if conf.get("space"):
            if conf.get("space").get("before"):
                self.space_before = conf["space"]["before"]
            if conf.get("space").get("after"):
                self.space_after = conf["space"]["after"]

    def __str__(self) -> str:
        return "".join(str(i) for i in (
            self.style_name, " ",
            self.font_default, " ",
            self.font_east_asia, " ",
            self.font_size, " ",
            self.font_color, " ",
            "space:(", self.space_before, " ", self.space_after, ") ",
            "bold-", self.font_bold, " ",
            "italic-", self.font_italic, " ",
            "underline-", self.font_underline, " ",
            "strike-", self.font_strike
        ))
