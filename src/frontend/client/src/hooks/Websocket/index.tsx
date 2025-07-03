import { useCallback, useEffect, useMemo } from "react";
import { useLinsightManager } from "../useLinsightManager";

// 每个会话单独分配一个 WebSocket实例
const connections: Record<string, WebSocket> = {};

export const useLinsightWebSocket = (sessionId) => {
    const { getLinsight, updateLinsight } = useLinsightManager()

    const task = useMemo(() => {
        const linsight = getLinsight(sessionId);
        return linsight
            ? { sessionId, running: linsight.status === 'running' }
            : { sessionId, running: false };
    }, [getLinsight, sessionId]);


    const connect = useCallback((id: string, msg: any) => {
        // 清理可能存在的旧连接
        if (connections[id]) {
            connections[id].close();
        }

        const websocket = new WebSocket(`wss://your-api-endpoint/sessions/${id}`);
        connections[id] = websocket;

        websocket.onopen = () => {
            console.log("WebSocket connection established!");
            websocket.send(JSON.stringify(msg)); 
        };

        websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('data :>> ', data);

            // 更新对应会话的执行信息
            // updateLinsight(sessionId, {
            //     content: data.content,
            //     title: data.title || undefined
            // });
        };

        websocket.onclose = () => {
            console.log(`WebSocket closed for session ${id}`);
            if (connections[id] === websocket) {
                delete connections[id];
            }
        };

        websocket.onerror = (error) => {
            console.error(`WebSocket error for session ${id}:`, error);
        };
    }, [])


    useEffect(() => {
        if (!task.running) return;

        // 当没有连接或连接已关闭时创建新连接
        if (!connections[task.sessionId] ||
            connections[task.sessionId].readyState !== WebSocket.OPEN) {
            const msg = { type: 'init' };
            connect(task.sessionId, msg);
        }
    }, [task])

    const stop = useCallback(() => {
        const ws = connections[sessionId];
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'stop' }));
        }
    }, [sessionId])

    const sendInput = useCallback((msg: any) => {
        const ws = connections[sessionId];
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
        }
    }, [sessionId]);


    return { stop, sendInput };
};