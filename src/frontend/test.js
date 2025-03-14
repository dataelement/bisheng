const fs = require('fs');
// 保存后的预置问题处理
// 读取原始 JSON 文件
const filePath = '/Users/shanghang/Downloads/成都银行POC v1.json'; // JSON 文件的路径
fs.readFile(filePath, 'utf8', (err, data) => {
    if (err) {
        console.error('读取文件失败:', err);
        return;
    }
    let str = data;
    // 解析 JSON 数据
    let jsonData;
    try {
        jsonData = JSON.parse(data);
    } catch (parseErr) {
        console.error('解析 JSON 失败:', parseErr);
        return;
    }

    // 修改 JSON 数据（此处可以根据需要修改）
    // 示例：修改某个字段
    const startNode = jsonData.nodes.find(node => node.data.type === 'start');
    const keys = startNode.data.group_params[1].params[2].value
    keys.map((item, index) => {
        if (item.value.trim()) {
            // 替换匹配模式为 'preset_question#' 后接单个数字的情况
            const regex = new RegExp(`preset_question#${index}"`, 'g');
            // 执行替换
            str = str.replaceAll(regex, `preset_question#${item.key}"`);
        }
    })

    // 将修改后的 JSON 数据转换为字符串
    // const updatedJson = JSON.stringify(jsonData); // 美化输出，空格为 2

    // 保存回原文件，覆盖原文件内容
    fs.writeFile(filePath, str, 'utf8', (writeErr) => {
        if (writeErr) {
            console.error('写入文件失败:', writeErr);
        } else {
            console.log('文件已成功更新！');
        }
    });
});