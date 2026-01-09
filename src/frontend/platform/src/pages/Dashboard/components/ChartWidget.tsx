'use client';

import React, { useEffect, useRef, useState } from 'react';

// 动态加载 echarts
const loadECharts = async () => {
    if ((window as any).echarts) {
        return (window as any).echarts;
    }

    const script = document.createElement('script');
    script.src = `${(window as any).__APP_ENV__?.BASE_URL || ''}/echarts.min.js`;
    script.type = 'module';

    return new Promise((resolve, reject) => {
        script.onload = () => {
            const checkECharts = setInterval(() => {
                if ((window as any).echarts) {
                    clearInterval(checkECharts);
                    resolve((window as any).echarts);
                }
            }, 100);
        };
        script.onerror = reject;
        document.head.appendChild(script);
    });
};

/**
 * 图表配置生成器
 */
const getChartOption = (type: string, data?: any): any => {
    const defaultColors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4'];

    switch (type) {
        case 'bar':
            return {
                title: {
                    text: '柱状图示例',
                    left: 'center',
                    top: 10,
                    textStyle: { fontSize: 14 }
                },
                color: defaultColors,
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'shadow' }
                },
                grid: {
                    left: '3%',
                    right: '4%',
                    bottom: '3%',
                    top: '20%',
                    containLabel: true
                },
                xAxis: {
                    type: 'category',
                    data: data?.xAxis || ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
                },
                yAxis: {
                    type: 'value'
                },
                series: [{
                    name: '访问量',
                    type: 'bar',
                    data: data?.series || [120, 200, 150, 80, 70, 110, 130],
                    itemStyle: {
                        borderRadius: [4, 4, 0, 0]
                    }
                },
            {
                    name: '访问量22',
                    type: 'bar',
                    data: data?.series || [10, 20, 15, 80, 70, 110, 130],
                    itemStyle: {
                        borderRadius: [4, 4, 0, 0]
                    }
                }]
            };

        case 'line':
            return {
                title: {
                    text: '折线图示例',
                    left: 'center',
                    top: 10,
                    textStyle: { fontSize: 14 }
                },
                color: defaultColors,
                tooltip: {
                    trigger: 'axis'
                },
                grid: {
                    left: '3%',
                    right: '4%',
                    bottom: '3%',
                    top: '20%',
                    containLabel: true
                },
                xAxis: {
                    type: 'category',
                    boundaryGap: false,
                    data: data?.xAxis || ['1月', '2月', '3月', '4月', '5月', '6月', '7月']
                },
                yAxis: {
                    type: 'value'
                },
                series: [
                    {
                        name: '用户数',
                        type: 'line',
                        smooth: true,
                        data: data?.series1 || [820, 932, 901, 934, 1290, 1330, 1320],
                        areaStyle: {
                            opacity: 0.3
                        }
                    },
                    {
                        name: '访问量',
                        type: 'line',
                        smooth: true,
                        data: data?.series2 || [620, 732, 701, 734, 1090, 1130, 1120],
                        areaStyle: {
                            opacity: 0.3
                        }
                    }
                ]
            };

        case 'pie':
            return {
                title: {
                    text: '饼图示例',
                    left: 'center',
                    top: 10,
                    textStyle: { fontSize: 14 }
                },
                color: defaultColors,
                tooltip: {
                    trigger: 'item',
                    formatter: '{a} <br/>{b}: {c} ({d}%)'
                },
                legend: {
                    orient: 'vertical',
                    right: 10,
                    top: 'center',
                    textStyle: { fontSize: 12 }
                },
                series: [{
                    name: '数据分布',
                    type: 'pie',
                    radius: ['40%', '70%'],
                    avoidLabelOverlap: false,
                    itemStyle: {
                        borderRadius: 8,
                        borderColor: '#fff',
                        borderWidth: 2
                    },
                    label: {
                        show: false,
                        position: 'center'
                    },
                    emphasis: {
                        label: {
                            show: true,
                            fontSize: 16,
                            fontWeight: 'bold'
                        }
                    },
                    labelLine: {
                        show: false
                    },
                    data: data?.data || [
                        { value: 1048, name: '搜索引擎' },
                        { value: 735, name: '直接访问' },
                        { value: 580, name: '邮件营销' },
                        { value: 484, name: '联盟广告' },
                        { value: 300, name: '视频广告' }
                    ]
                }]
            };

        case 'table':
            // 表格类型暂时返回简单的柱状图
            return {
                title: {
                    text: '表格数据',
                    left: 'center',
                    top: 10,
                    textStyle: { fontSize: 14 }
                },
                color: defaultColors,
                tooltip: {
                    trigger: 'axis'
                },
                grid: {
                    left: '3%',
                    right: '4%',
                    bottom: '3%',
                    top: '20%',
                    containLabel: true
                },
                xAxis: {
                    type: 'category',
                    data: ['产品A', '产品B', '产品C', '产品D', '产品E']
                },
                yAxis: {
                    type: 'value'
                },
                series: [{
                    name: '销量',
                    type: 'bar',
                    data: [320, 280, 350, 420, 390],
                    itemStyle: {
                        borderRadius: [4, 4, 0, 0]
                    }
                }]
            };

        default:
            return {
                title: {
                    text: '图表',
                    left: 'center'
                },
                series: []
            };
    }
};

/**
 * ECharts图表组件
 */
interface ChartWidgetProps {
    type: 'bar' | 'line' | 'pie' | 'table';
    data?: any;
    width?: number;
    height?: number;
}

export default function ChartWidget({ type, data, width, height }: ChartWidgetProps) {
    const chartRef = useRef<any>(null);
    const domRef = useRef<HTMLDivElement>(null);
    const [echartsLib, setEchartsLib] = useState<any>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // 加载ECharts库
    useEffect(() => {
        loadECharts()
            .then((echarts) => {
                setEchartsLib(echarts);
                setIsLoading(false);
            })
            .catch((err) => {
                console.error('Failed to load ECharts:', err);
                setError('加载图表库失败');
                setIsLoading(false);
            });
    }, []);

    // 初始化和更新图表
    useEffect(() => {
        if (!echartsLib || !domRef.current || isLoading) return;

        // 清理旧实例
        if (chartRef.current) {
            chartRef.current.dispose();
            chartRef.current = null;
        }

        try {
            // 初始化图表
            chartRef.current = echartsLib.init(domRef.current);
            const option = getChartOption(type, data);
            chartRef.current.setOption(option);
        } catch (err) {
            console.error('Failed to initialize chart:', err);
            setError('图表初始化失败');
        }

        return () => {
            if (chartRef.current) {
                chartRef.current.dispose();
                chartRef.current = null;
            }
        };
    }, [echartsLib, type, data, isLoading]);

    // 响应式调整大小
    useEffect(() => {
        if (!chartRef.current) return;

        const resizeObserver = new ResizeObserver(() => {
            chartRef.current?.resize();
        });

        if (domRef.current) {
            resizeObserver.observe(domRef.current);
        }

        const handleResize = () => {
            chartRef.current?.resize();
        };
        window.addEventListener('resize', handleResize);

        return () => {
            resizeObserver.disconnect();
            window.removeEventListener('resize', handleResize);
        };
    }, [echartsLib, chartRef.current]);

    if (isLoading) {
        return (
            <div className="w-full h-full flex items-center justify-center bg-gray-50 rounded">
                <div className="text-center">
                    <div className="text-2xl mb-2">⏳</div>
                    <p className="text-sm text-gray-500">加载图表中...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="w-full h-full flex items-center justify-center bg-red-50 rounded">
                <div className="text-center">
                    <div className="text-2xl mb-2">⚠️</div>
                    <p className="text-sm text-red-500">{error}</p>
                </div>
            </div>
        );
    }

    return (
        <div
            ref={domRef}
            className="w-full h-full"
            style={{ minHeight: '200px' }}
        />
    );
}
