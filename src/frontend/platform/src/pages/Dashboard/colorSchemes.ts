export interface ColorScheme {
    id: string;
    name: string;
    description: string;
    useCase: string;
    colors: {
        light: string[];
        dark: string[];
    };
    background: {
        light: string;
        dark: string;
    };
    text: {
        light: string;
        dark: string;
    };
    border: {
        light: string;
        dark: string;
    };
}

export const colorSchemes: ColorScheme[] = [
    {
        id: 'professional-blue',
        name: '专业蓝 - Professional Blue',
        description: '经典专业的蓝色系，传达信任与稳重',
        useCase: '金融、企业管理、数据分析',
        colors: {
            light: ['#3B82F6', '#60A5FA', '#93C5FD', '#BFDBFE', '#DBEAFE'],
            dark: ['#60A5FA', '#3B82F6', '#2563EB', '#1D4ED8', '#1E40AF'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'vibrant-green',
        name: '活力绿 - Vibrant Green',
        description: '清新自然的绿色系，象征成长与健康',
        useCase: '健康医疗、环保能源、教育培训',
        colors: {
            light: ['#10B981', '#34D399', '#6EE7B7', '#A7F3D0', '#D1FAE5'],
            dark: ['#34D399', '#10B981', '#059669', '#047857', '#065F46'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'tech-purple',
        name: '科技紫 - Tech Purple',
        description: '现代科技感的紫色系，彰显创新与智能',
        useCase: '科技产品、AI应用、创新创业',
        colors: {
            light: ['#8B5CF6', '#A78BFA', '#C4B5FD', '#DDD6FE', '#EDE9FE'],
            dark: ['#A78BFA', '#8B5CF6', '#7C3AED', '#6D28D9', '#5B21B6'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'energetic-orange',
        name: '能量橙 - Energetic Orange',
        description: '充满活力的橙色系，激发热情与积极',
        useCase: '电商零售、营销推广、社交媒体',
        colors: {
            light: ['#F59E0B', '#FBBF24', '#FCD34D', '#FDE68A', '#FEF3C7'],
            dark: ['#FBBF24', '#F59E0B', '#D97706', '#B45309', '#92400E'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'premium-rose',
        name: '高端玫瑰 - Premium Rose',
        description: '优雅精致的玫瑰色系，展现品质与格调',
        useCase: '时尚奢侈品、美容美妆、高端服务',
        colors: {
            light: ['#EC4899', '#F472B6', '#F9A8D4', '#FBCFE8', '#FCE7F3'],
            dark: ['#F472B6', '#EC4899', '#DB2777', '#BE185D', '#9F1239'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'ocean-teal',
        name: '海洋青 - Ocean Teal',
        description: '沉稳清澈的青色系，传递专业与可靠',
        useCase: '医疗健康、科研机构、咨询服务',
        colors: {
            light: ['#14B8A6', '#2DD4BF', '#5EEAD4', '#99F6E4', '#CCFBF1'],
            dark: ['#2DD4BF', '#14B8A6', '#0D9488', '#0F766E', '#115E59'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'sunset-gradient',
        name: '日落渐变 - Sunset Gradient',
        description: '温暖多彩的渐变色系，富有感染力',
        useCase: '创意设计、娱乐文化、品牌营销',
        colors: {
            light: ['#F59E0B', '#EF4444', '#EC4899', '#A855F7', '#6366F1'],
            dark: ['#FBBF24', '#F87171', '#F472B6', '#C084FC', '#818CF8'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'minimalist-gray',
        name: '极简灰 - Minimalist Gray',
        description: '高级中性的灰色系，注重内容本身',
        useCase: '新闻资讯、工具应用、极简设计',
        colors: {
            light: ['#64748B', '#94A3B8', '#CBD5E1', '#E2E8F0', '#F1F5F9'],
            dark: ['#94A3B8', '#64748B', '#475569', '#334155', '#1E293B'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'rainbow-spectrum',
        name: '彩虹光谱 - Rainbow Spectrum',
        description: '完整的彩虹色谱，展现丰富多元的数据维度',
        useCase: '多维度数据分析、教育科普、儿童产品',
        colors: {
            light: ['#EF4444', '#F59E0B', '#EAB308', '#22C55E', '#3B82F6', '#8B5CF6', '#EC4899'],
            dark: ['#F87171', '#FBBF24', '#FDE047', '#4ADE80', '#60A5FA', '#A78BFA', '#F472B6'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'warm-palette',
        name: '暖色盘 - Warm Palette',
        description: '温暖舒适的暖色调组合，营造友好亲切的氛围',
        useCase: '餐饮美食、家居生活、社区服务',
        colors: {
            light: ['#DC2626', '#EA580C', '#F59E0B', '#EAB308', '#FB923C'],
            dark: ['#F87171', '#FB923C', '#FBBF24', '#FCD34D', '#FDBA74'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'cool-palette',
        name: '冷色盘 - Cool Palette',
        description: '清爽沉静的冷色调组合，传递冷静专业的印象',
        useCase: '科技软件、医疗健康、金融保险',
        colors: {
            light: ['#0EA5E9', '#06B6D4', '#14B8A6', '#10B981', '#8B5CF6'],
            dark: ['#38BDF8', '#22D3EE', '#2DD4BF', '#34D399', '#A78BFA'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'candy-pastel',
        name: '糖果马卡龙 - Candy Pastel',
        description: '柔和甜美的马卡龙色系，充满治愈感',
        useCase: '儿童教育、美妆时尚、文创设计',
        colors: {
            light: ['#F9A8D4', '#FBCFE8', '#DDD6FE', '#BFDBFE', '#A7F3D0'],
            dark: ['#F472B6', '#E879F9', '#C084FC', '#60A5FA', '#34D399'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'neon-bright',
        name: '霓虹荧光 - Neon Bright',
        description: '高饱和度的霓虹色系，极具视觉冲击力',
        useCase: '电竞游戏、音乐娱乐、潮流文化',
        colors: {
            light: ['#FF006E', '#FF9500', '#FFED00', '#00F5FF', '#B967FF'],
            dark: ['#FF1A8C', '#FFB84D', '#FFF566', '#33F7FF', '#D499FF'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'earth-natural',
        name: '大地自然 - Earth Natural',
        description: '沉稳温润的大地色系，贴近自然本真',
        useCase: '环保公益、农业农产、文化艺术',
        colors: {
            light: ['#92400E', '#B45309', '#CA8A04', '#65A30D', '#0F766E'],
            dark: ['#D97706', '#F59E0B', '#EAB308', '#84CC16', '#14B8A6'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'complementary-contrast',
        name: '互补对比 - Complementary Contrast',
        description: '高对比度的互补色组合，强化数据差异',
        useCase: '对比分析、竞品研究、AB测试',
        colors: {
            light: ['#3B82F6', '#F59E0B', '#10B981', '#EF4444', '#8B5CF6'],
            dark: ['#60A5FA', '#FBBF24', '#34D399', '#F87171', '#A78BFA'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'morandi-muted',
        name: '莫兰迪灰调 - Morandi Muted',
        description: '高级莫兰迪色系，低饱和度彰显品味',
        useCase: '高端品牌、艺术设计、精品电商',
        colors: {
            light: ['#9CA3AF', '#A8A29E', '#D1C4B0', '#B4C7C9', '#C7B8D4'],
            dark: ['#D1D5DB', '#D6D3D1', '#E7D4BC', '#CFDFE1', '#DDD2E9'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'vivid-rainbow',
        name: '鲜艳彩虹 - Vivid Rainbow',
        description: '高亮度的多彩组合，充满活力与创意',
        useCase: '创意工作室、儿童产品、节日活动',
        colors: {
            light: ['#FF4D6A', '#FF9500', '#FFD60A', '#34C759', '#007AFF', '#AF52DE', '#FF2D55'],
            dark: ['#FF6B82', '#FFB84D', '#FFE766', '#5DDC7A', '#3399FF', '#C97FF0', '#FF5A72'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'tropical-paradise',
        name: '热带天堂 - Tropical Paradise',
        description: '热情奔放的热带色彩，洋溢夏日活力',
        useCase: '旅游度假、运动健身、生活方式',
        colors: {
            light: ['#FF6B9D', '#FF8C42', '#FFC93C', '#07D092', '#00B4D8'],
            dark: ['#FF8AB8', '#FFA366', '#FFD866', '#2CE3AC', '#33C9EC'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
    {
        id: 'autumn-harvest',
        name: '秋日丰收 - Autumn Harvest',
        description: '温暖丰盈的秋季色调，传递收获与温馨',
        useCase: '农业食品、感恩节庆、温暖品牌',
        colors: {
            light: ['#C2410C', '#D97706', '#CA8A04', '#B45309', '#92400E'],
            dark: ['#F97316', '#FB923C', '#FDE047', '#FDBA74', '#D97706'],
        },
        background: {
            light: '#FFFFFF',
            dark: '#0F172A',
        },
        text: {
            light: '#1E293B',
            dark: '#E2E8F0',
        },
        border: {
            light: '#E2E8F0',
            dark: '#334155',
        },
    },
];




export const convertToEChartsTheme = (scheme: ColorScheme, mode: 'light' | 'dark' = 'light') => {
    const isDark = mode === 'dark';
    const mainColors = scheme.colors[mode];
    const textColor = scheme.text[mode];
    const borderColor = scheme.border[mode];
    const bgColor = scheme.background[mode];

    return {
        color: mainColors,
        backgroundColor: bgColor,
        textStyle: {
            color: textColor
        },
        line: {
            itemStyle: { borderWidth: 1 },
            lineStyle: { width: 2 },
            symbolSize: 4,
            symbol: 'emptyCircle',
            smooth: false
        },
        categoryAxis: {
            axisLine: { show: true, lineStyle: { color: borderColor } },
            axisTick: { show: true, lineStyle: { color: borderColor } },
            axisLabel: { show: true, color: textColor },
            splitLine: { show: false }
        },
        valueAxis: {
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { show: true, color: textColor },
            splitLine: { show: true, lineStyle: { color: borderColor, type: 'dashed' } }
        },
        legend: {
            textStyle: { color: textColor }
        },
        tooltip: {
            axisPointer: {
                lineStyle: { color: borderColor, width: 1 },
                crossStyle: { color: borderColor, width: 1 }
            }
        }
    };
};

// defult metric style
export const getDefaultMetricStyle = (title, subtitle) => ({
    "bgColor": "",
    "showAxis": true,
    "showGrid": true,
    "xAxisBold": false,
    "yAxisBold": false,
    "legendBold": false,
    "showLegend": true,
    "themeColor": "",
    "xAxisAlign": "",
    "xAxisColor": "",
    "xAxisTitle": "",
    "yAxisAlign": "",
    "yAxisColor": "",
    "yAxisTitle": "",
    "xAxisUnderline": false,
    "yAxisUnderline": false,
    "legendUnderline": false,
    "legendAlign": "",
    "legendColor": "",
    "xAxisItalic": false,
    "yAxisItalic": false,
    "legendItalic": false,
    "showDataLabel": true,
    "xAxisFontSize": 0,
    "yAxisFontSize": 0,
    "legendFontSize": 0,
    "legendPosition": "",
    "showSubtitle": true,
    title,
    "titleFontSize": 14,
    "titleColor": "#0F172A",
    "titleAlign": "left",
    "titleBold": false,
    "titleItalic": false,
    "titleUnderline": false,
    subtitle,
    "subtitleFontSize": 14,
    "subtitleColor": "#666",
    "subtitleAlign": "left",
    "subtitleBold": false,
    "subtitleItalic": false,
    "subtitleUnderline": false,
    "metricFontSize": 28,
    "metricColor": "#4882f6",
    "metricAlign": "start",
    "metricBold": true,
    "metricItalic": false,
    "metricUnderline": false,
})