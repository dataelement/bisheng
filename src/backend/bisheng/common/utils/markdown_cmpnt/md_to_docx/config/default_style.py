#  参数解释。注意冒号或短横线后必须接一个空格，不能省略。
#
#  font:
#    default: 西文字体，默认 [Times New Roman]
#    east-asia: 中文字体，默认 [宋体]
#    size: 字体大小，默认 [12]，单位：pt
#    color: RGB颜色的 16 进制值，必须为字符串，默认 ["000000"] 纯黑色
#    extra: 额外的样式，默认不添加这些样式。支持下列样式，有则生效，无则忽略
#    - bold 加粗
#    - italic 斜体
#    - underline 下划线
#    - strike 删除线
#  first-line-indent: 首行缩进，默认 [0]，单位：倍
#  line-spacing: 行距，默认 [1.2] 单位：倍，表示行距设置为 1.2 倍行高，
#  space:
#    before 段前空格，默认 [0] pt
#    after: 段后空格，默认 [0] pt

# h1~h4表示1到4级标题
style_conf = {
    "h1":
        {
            "font":
                {
                    "default": "黑体",
                    "east-asia": "黑体",
                    "size": 22
                },
            "line-spacing": 0,
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
