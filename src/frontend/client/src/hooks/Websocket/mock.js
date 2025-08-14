export class MockWebSocket {
    constructor(url) {
        this.url = url;
        this.readyState = WebSocket.CONNECTING;
        this.onopen = null;
        this.onmessage = null;
        this.onclose = null;
        this.onerror = null;
        this.sessionId = url.split('/').pop();
        this.currentTaskIndex = 0;
        this.userInputCallback = null;
        this.stopped = false;
        this.tasks = []; // 存储所有任务
        this.lastUserInput = null;

        // 初始化任务
        this.initTasks();

        // 模拟连接成功
        setTimeout(() => {
            this.readyState = WebSocket.OPEN;
            if (this.onopen) this.onopen();
            this.startTasks();
        }, 100);
    }

    initTasks() {
        // 基于实际数据结构创建任务
        this.tasks = [{
                id: "46393f07e99149dea490576706288d2e",
                step_id: "step_1",
                description: "检查冰箱是否处于良好状态，并确保其内部清洁无杂物。",
                profile: "准备机器人",
                target: "确保冰箱适合大象进入",
                sop: "检查冰箱状态并清洁",
                prompt: "请检查冰箱的状态并确保其内部清洁无杂物。",
                input: ["query"],
                next_id: ["123ab3ea6ef042f4b6a5ef81774e8285"],
                requiresUserInput: true // 标记需要用户输入
            },
            {
                id: "123ab3ea6ef042f4b6a5ef81774e8285",
                step_id: "step_2",
                description: "联系专业搬运团队到达现场；利用起重设备平稳地将大象从当前位置转移至冰箱附近。",
                profile: "搬运机器人",
                target: "将大象移动到冰箱附近",
                sop: "联系搬运团队并使用起重设备搬运大象",
                prompt: "请联系专业搬运团队到达现场，并利用起重设备平稳地将大象从当前位置转移至冰箱附近。",
                input: ["step_1"],
                next_id: ["d86b23da4e344098bde846bcfd444d04"]
            },
            {
                id: "d86b23da4e344098bde846bcfd444d04",
                step_id: "step_3",
                description: "如果必要，拆卸冰箱门以便于大象进入；确保周围环境安全，避免任何可能对大象造成伤害的因素。",
                profile: "调整机器人",
                target: "调整冰箱门以方便大象进入",
                sop: "拆卸冰箱门并确保环境安全",
                prompt: "如果必要，请拆卸冰箱门以便于大象进入，并确保周围环境安全，避免任何可能对大象造成伤害的因素。",
                input: ["step_2"],
                next_id: ["12cbe4bc49884c42a92e27952e59ea86"]
            },
            {
                id: "12cbe4bc49884c42a92e27952e59ea86",
                step_id: "step_4",
                description: "在专业人士指导下，温和地引导大象走进冰箱；一旦大象完全进入冰箱后，重新安装冰箱门并关闭。",
                profile: "引导机器人",
                target: "引导大象进入冰箱并关闭冰箱门",
                sop: "引导大象进入冰箱并关闭冰箱门",
                prompt: "请在专业人士指导下，温和地引导大象走进冰箱。一旦大象完全进入冰箱后，重新安装冰箱门并关闭。",
                input: ["step_3"],
                next_id: ["c7a2f1a0932d4c709675dcb1eaa6dd68"]
            },
            {
                id: "c7a2f1a0932d4c709675dcb1eaa6dd68",
                step_id: "step_5",
                description: "清理现场，确保所有使用的设备归位。",
                profile: "收尾机器人",
                target: "清理现场并归位设备",
                sop: "清理现场并归位设备",
                prompt: "请清理现场，确保所有使用的设备归位。",
                input: ["step_4"],
                next_id: null
            }
        ];
    }

    startTasks() {
        if (this.stopped) return;

        // 1. 发送任务生成事件
        this.sendTaskGenerate();

        // 2. 开始执行第一个任务
        setTimeout(() => this.executeTask(this.tasks[0]), 300);
    }

    sendTaskGenerate() {
        this.sendMessage({
            event_type: "task_generate",
            data: {
                tasks: this.tasks.map(task => ({
                    session_version_id: this.sessionId,
                    parent_task_id: null,
                    previous_task_id: null,
                    next_task_id: task.next_id ? task.next_id[0] : null,
                    task_type: "single",
                    task_data: {
                        step_id: task.step_id,
                        description: task.description,
                        profile: task.profile,
                        target: task.target,
                        sop: task.sop,
                        prompt: task.prompt,
                        input: task.input,
                        node_loop: false,
                        id: task.id,
                        next_id: task.next_id
                    },
                    id: task.id,
                    input_prompt: null,
                    user_input: null,
                    history: null,
                    status: "not_started",
                    result: null,
                    create_time: new Date().toISOString()
                })),
                timestamp: Date.now() / 1000
            }
        });
    }

    async executeTask(task) {
        if (this.stopped || !task) return;

        // 发送任务开始事件
        this.sendTaskStart(task);

        // 模拟任务执行时间
        await this.delay(800);

        // 检查是否需要用户输入
        if (task.requiresUserInput && !this.stopped) {
            // 发送用户输入请求
            this.sendUserInputRequest(task);

            // 等待用户输入
            await new Promise(resolve => {
                this.userInputCallback = resolve;
            });

            if (this.stopped) return;

            // 发送用户输入完成事件
            this.sendUserInputCompleted(task);

            // 模拟用户输入后处理时间
            await this.delay(600);
        }

        // 发送任务结束事件
        this.sendTaskEnd(task);

        // 如果有下一个任务，继续执行
        if (task.next_id && task.next_id.length > 0 && !this.stopped) {
            const nextTaskId = task.next_id[0];
            const nextTask = this.tasks.find(t => t.id === nextTaskId);
            if (nextTask) {
                setTimeout(() => this.executeTask(nextTask), 300);
            }
        } else if (!this.stopped) {
            // 所有任务完成后发送最终结果
            this.sendFinalResult();
        }
    }

    sendTaskStart(task) {
        this.sendMessage({
            event_type: "task_start",
            data: {
                parent_task_id: null,
                previous_task_id: null,
                task_type: "single",
                input_prompt: null,
                history: null,
                result: null,
                create_time: new Date().toISOString(),
                session_version_id: this.sessionId,
                next_task_id: task.next_id ? task.next_id[0] : null,
                task_data: {
                    id: task.id,
                    sop: task.sop,
                    input: task.input,
                    prompt: task.prompt,
                    target: task.target,
                    next_id: task.next_id,
                    profile: task.profile,
                    step_id: task.step_id,
                    node_loop: false,
                    description: task.description
                },
                user_input: null,
                status: "in_progress",
                id: task.id,
                update_time: new Date().toISOString()
            },
            timestamp: Date.now() / 1000
        });
    }

    sendUserInputRequest(task) {
        this.sendMessage({
            event_type: "user_input",
            data: {
                task_id: task.id,
                call_reason: "我需要确认冰箱的状态和清洁情况。请检查冰箱是否处于良好状态，并且内部已经清洁无杂物。可以的话，请告诉我冰箱的尺寸以及它当前的状态。"
            },
            timestamp: Date.now() / 1000
        });
    }

    sendUserInputCompleted(task) {
        this.sendMessage({
            event_type: "user_input_completed",
            data: {
                session_version_id: this.sessionId,
                parent_task_id: null,
                previous_task_id: null,
                next_task_id: task.next_id ? task.next_id[0] : null,
                task_type: "single",
                task_data: {
                    id: task.id,
                    sop: task.sop,
                    input: task.input,
                    prompt: task.prompt,
                    target: task.target,
                    next_id: task.next_id,
                    profile: task.profile,
                    step_id: task.step_id,
                    node_loop: false,
                    description: task.description
                },
                input_prompt: "我需要确认冰箱的状态和清洁情况。请检查冰箱是否处于良好状态，并且内部已经清洁无杂物。可以的话，请告诉我冰箱的尺寸以及它当前的状态。",
                user_input: this.lastUserInput || "确认",
                history: null,
                status: "user_input_completed",
                result: null,
                id: task.id,
                create_time: new Date().toISOString(),
                update_time: new Date().toISOString()
            },
            timestamp: Date.now() / 1000
        });
    }

    sendTaskEnd(task) {
        this.sendMessage({
            event_type: "task_end",
            data: {
                parent_task_id: null,
                previous_task_id: null,
                task_type: "single",
                input_prompt: task.id === "c7a2f1a0932d4c709675dcb1eaa6dd68" ?
                    "确认现场清理和设备归位情况" : `确认${task.target}步骤是否完成`,
                history: null,
                result: {
                    answer: `好的，${task.target}已完成。\n\n任务总结:\n${this.generateTaskSummary()}`
                },
                create_time: new Date().toISOString(),
                session_version_id: this.sessionId,
                next_task_id: task.next_id ? task.next_id[0] : null,
                task_data: {
                    id: task.id,
                    sop: task.sop,
                    input: task.input,
                    prompt: task.prompt,
                    target: task.target,
                    next_id: task.next_id,
                    profile: task.profile,
                    step_id: task.step_id,
                    node_loop: false,
                    description: task.description
                },
                user_input: this.lastUserInput || "确认",
                status: "success",
                id: task.id,
                update_time: new Date().toISOString()
            },
            timestamp: Date.now() / 1000
        });
    }

    generateTaskSummary() {
        return this.tasks.map((task, index) =>
            `${index + 1}. **${task.profile}**: ${task.description}`
        ).join('\n');
    }

    sendFinalResult() {
        this.sendMessage({
            event_type: "final_result",
            data: {
                user_id: 3,
                question: "# 把大象装进冰箱的标准操作流程 (SOP)\n\n## 问题概述\n\n本SOP旨在提供一个清晰的步骤指南，用于将大型物体（以大象为例）安全地安置到指定空间内（如冰箱）。此过程假设所有物理限制已被解决，例如冰箱大小足够容纳大象。适用范围包括但不限于需要将大体积物品移动并妥善存放的情况。\n\n## 所需工具和资源\n\n- **超大尺寸冰箱** - 确保冰箱内部空间足以容纳大象。\n- **起重设备** - 如起重机或叉车，用于搬运大象。\n- **专业搬运团队** - 具备处理大型动物经验的专业人员。\n- **安全装备** - 包括但不限于手套、护目镜等个人防护装备。\n\n## 步骤说明\n\n1. **准备阶段**\n\n   - 检查冰箱是否处于良好状态，并确保其内部清洁无杂物。\n2. **搬运大象**\n\n   - 联系专业搬运团队到达现场。\n   - 利用起重设备平稳地将大象从当前位置转移至冰箱附近。\n3. **调整冰箱门**\n\n   - 如果必要，拆卸冰箱门以便于大象进入。\n   - 确保周围环境安全，避免任何可能对大象造成伤害的因素。\n4. **引导大象进入冰箱**\n\n   - 在专业人士指导下，温和地引导大象走进冰箱。\n   - 一旦大象完全进入冰箱后，重新安装冰箱门并关闭。\n5. **完成与确认**\n\n   - 清理现场，确保所有使用的设备归位。\n\n以上步骤完成后，即完成了将大象装入冰箱的过程。请注意，在实际操作中应始终遵循当地法律法规以及动物保护原则。",
                personal_knowledge_enabled: false,
                files: [],
                output_result: {
                    answer: "所有步骤已完成，大象已成功装入冰箱。"
                },
                score: null,
                has_reexecute: false,
                id: this.sessionId,
                update_time: new Date().toISOString(),
                session_id: "7671de26445c408c89a8060dfb52a30b",
                tools: [],
                org_knowledge_enabled: false,
                sop: "# 把大象装进冰箱的标准操作流程 (SOP)\n\n## 问题概述\n\n本SOP旨在提供一个清晰的步骤指南，用于将大型物体（以大象为例）安全地安置到指定空间内（如冰箱）。此过程假设所有物理限制已被解决，例如冰箱大小足够容纳大象。适用范围包括但不限于需要将大体积物品移动并妥善存放的情况。\n\n## 所需工具和资源\n\n- **超大尺寸冰箱** - 确保冰箱内部空间足以容纳大象。\n- **起重设备** - 如起重机或叉车，用于搬运大象。\n- **专业搬运团队** - 具备处理大型动物经验的专业人员。\n- **安全装备** - 包括但不限于手套、护目镜等个人防护装备。\n\n## 步骤说明\n\n1. **准备阶段**\n\n   - 检查冰箱是否处于良好状态，并确保其内部清洁无杂物。\n2. **搬运大象**\n\n   - 联系专业搬运团队到达现场。\n   - 利用起重设备平稳地将大象从当前位置转移至冰箱附近。\n3. **调整冰箱门**\n\n   - 如果必要，拆卸冰箱门以便于大象进入。\n   - 确保周围环境安全，避免任何可能对大象造成伤害的因素。\n4. **引导大象进入冰箱**\n\n   - 在专业人士指导下，温和地引导大象走进冰箱。\n   - 一旦大象完全进入冰箱后，重新安装冰箱门并关闭。\n5. **完成与确认**\n\n   - 清理现场，确保所有使用的设备归位。\n\n以上步骤完成后，即完成了将大象装入冰箱的过程。请注意，在实际操作中应始终遵循当地法律法规以及动物保护原则。\n",
                status: "completed",
                execute_feedback: null,
                version: new Date().toISOString(),
                create_time: new Date().toISOString()
            },
            timestamp: Date.now() / 1000
        });
    }

    sendMessage(data) {
        if (this.onmessage && !this.stopped) {
            this.onmessage({
                data: JSON.stringify(data)
            });
        }
    }

    send(data) {
        if (this.stopped) return;

        try {
            const message = JSON.parse(data);

            // 处理用户输入
            if (message.user_input) {
                this.lastUserInput = message.user_input;
                if (this.userInputCallback) {
                    this.userInputCallback();
                    this.userInputCallback = null;
                }
            }

            // 处理停止请求
            if (message.action === 'stop') {
                this.close(1000, "Stopped by user");
            }
        } catch (e) {
            console.error("Error parsing message:", e);
        }
    }

    close(code = 1000, reason = "Completed") {
        this.readyState = WebSocket.CLOSED;
        this.stopped = true;
        if (this.onclose) this.onclose({
            code,
            reason
        });
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}