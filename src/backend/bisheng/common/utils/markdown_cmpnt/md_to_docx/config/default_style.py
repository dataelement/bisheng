#  Parameter explanation. Note that colon or dash must be followed by a space and cannot be omitted.
#
#  font:
#    default: Western fonts, default [Times New Roman]
#    east-asia: Chinese font, default [Song Ti]
#    size: Font Size (Default) [12]<g id="Bold">Employer: </g>pt
#    color: RGBColorful 16 Metric value, must be a string, default ["000000"] pure black
#    extra: Extra styles, do not add these styles by default. The following styles are supported, effective if there is, ignored if there is none
#    - bold bolded
#    - italic Italic
#    - underline LOW LINE
#    - strike Strikethrough
#  first-line-indent: First line indent, default [0], unit: times
#  line-spacing: Line spacing, default [1.2] Unit: times, indicates line spacing is set to 1.2 Double row height,
#  space:
#    before Space before paragraph, default [0] pt
#    after: Space after paragraph, default [0] pt

# h1~h4Show1to4Level Title
style_conf = {
    "h1":
        {
            "font":
                {
                    "default": "黑体",
                    "east-asia": "黑体",
                    "size": 22
                },
            "line-spacing": 1.2,
            "space":
                {
                    "before": 11,
                    "after": 11
                }
        },
    "h2":
        {
            "font":
                {
                    "default": "黑体",
                    "east-asia": "黑体",
                    "size": 18
                },
            "line-spacing": 1.2,
            "space":
                {
                    "before": 11,
                    "after": 11
                }
        },
    "h3":
        {
            "font":
                {
                    "default": "黑体",
                    "east-asia": "黑体",
                    "size": 14
                },
            "line-spacing": 1.2,
            "space":
                {
                    "before": 11,
                    "after": 11
                }
        },
    "h4":
        {
            "font":
                {
                    "default": "Times New Roman",
                    "east-asia": "楷体",
                    "size": 12,
                    "extra":
                        [
                            "bold"
                        ]
                },
            "line-spacing": 1.2,
            "space":
                {
                    "before": 11,
                    "after": 11
                }
        },
    "normal":
        {
            "font":
                {
                    "default": "Times New Roman",
                    "east-asia": "宋体",
                    "size": 12,
                    "color": "000000"
                },
            "line-spacing": 1.3,
            "space":
                {
                    "before": 7,
                    "after": 7
                }
        }
}
