import { Button } from "@/components/bs-ui/button";
import { saveThemeApi } from "@/controllers/API";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import Example from "./Example";
import HSLitem from "./HSLitem";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { Label } from "@/components/bs-ui/label";

const defaultTheme = {
    '--background': { h: 0, s: 0, l: 1 },
    '--foreground': { h: 222.2, s: 0.474, l: 0.112 },
    '--muted': { h: 210, s: 0.4, l: 0.98 },
    '--muted-foreground': { h: 215.4, s: 0.163, l: 0.469 },
    '--popover': { h: 0, s: 0, l: 1 },
    '--popover-foreground': { h: 222.2, s: 0.474, l: 0.112 },
    '--card': { h: 0, s: 0, l: 1 },
    '--card-foreground': { h: 222.2, s: 0.474, l: 0.112 },
    '--border': { h: 214.3, s: 0.218, l: 0.914 },
    '--input': { h: 223, s: 0.48, l: 0.44 },
    '--primary': { h: 220, s: 0.98, l: 0.45 },
    '--primary-foreground': { h: 210, s: 0.4, l: 0.98 },
    '--secondary': { h: 210, s: 0.4, l: 0.961 },
    '--secondary-foreground': { h: 222.2, s: 0.474, l: 0.112 },
    '--accent': { h: 210, s: 0.3, l: 0.961 },
    '--accent-foreground': { h: 222.2, s: 0.474, l: 0.112 },
    '--destructive': { h: 0, s: 1, l: 0.5 },
    '--destructive-foreground': { h: 210, s: 0.4, l: 0.98 },
    '--black-button': { h: 0, s: 0, l: 0.07 },
};

const themeKeys = {
    "--primary": "主题色",
    "--primary-foreground": "主题前景色",
    "--background": "背景色",
    "--foreground": "前景色",
    "--muted": "柔和背景色",
    "--muted-foreground": "柔和前景色",
    "--card": "卡片背景色",
    "--card-foreground": "卡片前景色",
    "--popover": "弹出框背景色",
    "--popover-foreground": "弹出框前景色",
    "--border": "边框色",
    "--input": "输入框边框色",
    "--secondary": "次要按钮背景色",
    "--secondary-foreground": "次要按钮前景色",
    "--accent": "强调色",
    "--accent-foreground": "强调前景色",
    "--destructive": "警告按钮背景色",
    "--destructive-foreground": "警告按钮前景色",
    "--ring": "聚焦边框色",
    "--radius": "圆角半径",
    "--warning": "警告色",
    "--warning-foreground": "警告前景色",
    '--black-button': '黑按钮',
};

export default function Theme() {
    const [theme, setTheme] = useState(Object.keys(window.ThemeStyle.comp).length ? window.ThemeStyle.comp : { ...defaultTheme });
    const [bg, setBg] = useState(window.ThemeStyle.bg || 'logo')

    const applyTheme = (theme) => {
        Object.keys(theme).forEach(key => {
            document.documentElement.style.setProperty(key, handleHSLtoStr(theme[key]));
        });
        setTheme(theme);
        window.ThemeStyle = { comp: theme, bg }
        saveThemeApi(JSON.stringify({ comp: theme }))
    };

    // hsl -> '220 98% 95%'
    const handleHSLtoStr = (hsl) => {
        return `${hsl.h} ${hsl.s * 100}% ${hsl.l * 100}%`
    }

    const handleHSLChange = (name, hsl) => {
        const newTheme = {
            ...theme,
            [name]: hsl,
        };
        setTheme(newTheme);
        document.documentElement.style.setProperty(name, handleHSLtoStr(hsl));
        // save
        window.ThemeStyle = { comp: newTheme, bg }
        saveThemeApi(JSON.stringify({ comp: newTheme }))
    };


    return <div className="flex justify-center border-t bg-accent">
        <div className="w-96 py-4 pr-8 border-r ">
            <p className="flex justify-between items-center mb-4">
                <span className="text-lg">颜色配置</span>
                <Button className="right" variant="link" onClick={e => applyTheme({ ...defaultTheme })}><RefreshCw className="mr-1 size-4" />还原</Button>
            </p>
            <div className="grid grid-cols-2 gap-2 gap-x-8 my-8">
                {
                    Object.keys(theme).map(key => {
                        return <HSLitem key={key} label={themeKeys[key]} name={key} value={theme[key]} onChange={handleHSLChange} />
                    })
                }
            </div>
            <p className="flex justify-between items-center mb-4">
                <span className="text-lg">工作流背景配置</span>
            </p>
            <RadioGroup value={bg} onValueChange={(val) => {
                window.ThemeStyle.bg = val
                saveThemeApi(JSON.stringify({ comp: theme, bg: val }))
                setBg(val)
            }}
                className="flex space-x-2 h-[20px] mt-4 mb-6">
                <div>
                    <Label className="flex justify-center">
                        <RadioGroupItem className="mr-2" value="logo" />BISHENG logo
                    </Label>
                </div>
                <div>
                    <Label className="flex justify-center">
                        <RadioGroupItem className="mr-2" value="gradient" />主题色渐变效果
                    </Label>
                </div>
            </RadioGroup>
        </div>
        <div className="px-4 py-4 bg-card">
            <p className="text-xl mb-4">组件预览</p>
            <div>
                {/* 组件列表 */}
                <Example />
            </div>
        </div>
    </div>
};
