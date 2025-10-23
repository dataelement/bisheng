import React, { useState, useEffect, useRef } from 'react';

const VoiceRecordingIcon = ({
    size = 28,
    onClick,
    circleColor = '#f0f0f0',
    barColor = 'black'
}) => {
    const [bars, setBars] = useState([0, 0, 0, 0, 0]);
    const animationRef = useRef<any>(null);

    // 生成明显的随机波形
    const generateWave = () => {
        // 强制每条竖线有明显高度差异（0.2-1.0范围）
        return [
            0.2 + Math.random() * 0.5,  // 第一条：低幅度波动
            0.3 + Math.random() * 0.7,  // 第二条：中幅度
            0.5 + Math.random() * 0.5,  // 第三条：高幅度（最明显）
            0.3 + Math.random() * 0.7,  // 第四条：中幅度
            0.2 + Math.random() * 0.5   // 第五条：低幅度
        ];
    };

    // 动画循环（每100ms强制更新一次，确保肉眼可见）
    const animate = () => {
        setBars(generateWave());
        animationRef.current = setTimeout(animate, 200); // 改用setTimeout确保固定间隔
    };

    // 组件挂载时启动动画，卸载时清理
    useEffect(() => {
        animate();
        return () => clearTimeout(animationRef.current);
    }, []);

    const innerSize = size * 0.6;

    return (
        <div
            style={{
                width: size,
                height: size,
                borderRadius: '50%',
                // backgroundColor: circleColor,
                // border: '1px solid #e0e0e0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
            }}
            onClick={onClick}
        >
            <div
                style={{
                    width: innerSize,
                    height: innerSize * 0.9, // 增加高度占比，让波动更明显
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                }}
            >
                {bars.map((height, i) => (
                    <div
                        key={i}
                        style={{
                            width: innerSize * 0.07, // 加宽竖线，增强视觉效果
                            height: height * innerSize * 0.9,
                            backgroundColor: barColor,
                            margin: `0 ${innerSize * 0.06}px`,
                            borderRadius: 1,
                        }}
                    />
                ))}
            </div>
        </div>
    );
};

export default VoiceRecordingIcon;