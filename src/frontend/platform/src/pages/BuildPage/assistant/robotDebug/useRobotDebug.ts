import { getRobotDebugContext, runRobotDebug, type DebugContext, type DebugEvent, type DebugHistoryTurn } from "@/controllers/API/eplusDebug";
import { useCallback, useEffect, useRef, useState } from "react";

export type DebugTurn = {
  id: string;
  question: string;
  answer: string;
  events: DebugEvent[];
  state: "running" | "completed" | "failed" | "stopped";
};

export function useRobotDebug(assistantId: string) {
  const [context, setContext] = useState<DebugContext | null>(null);
  const [turns, setTurns] = useState<DebugTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const history = useRef<DebugHistoryTurn[]>([]);

  const clear = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    history.current = [];
    setTurns([]);
    setBusy(false);
    setError(false);
  }, []);

  const loadContext = useCallback(async (userId?: number) => {
    clear();
    const epoch = generation.current;
    const next = new AbortController();
    controller.current = next;
    setContext(null);
    setLoading(true);
    try {
      const result = await getRobotDebugContext(assistantId, userId, next.signal);
      if (epoch === generation.current) setContext(result);
    } catch {
      if (epoch === generation.current && !next.signal.aborted) setError(true);
    } finally {
      if (epoch === generation.current) { controller.current = null; setLoading(false); }
    }
  }, [assistantId, clear]);

  useEffect(() => {
    void loadContext();
    return () => { generation.current += 1; controller.current?.abort(); history.current = []; };
  }, [loadContext]);

  const send = async (query: string) => {
    if (controller.current || !context || !query.trim() || query.trim().length > 4096) return;
    const next = new AbortController();
    controller.current = next;
    const epoch = generation.current;
    const turn: DebugTurn = { id: crypto.randomUUID(), question: query.trim(), answer: "", events: [], state: "running" };
    setBusy(true);
    setError(false);
    setTurns(current => [...current, { ...turn }].slice(-20));
    const update = () => {
      if (epoch === generation.current) setTurns(current => current.map(item => item.id === turn.id ? { ...turn, events: [...turn.events] } : item));
    };
    try {
      await runRobotDebug({ assistantId, query: turn.question, testUserId: context.test_user_id, history: history.current }, event => {
        if (epoch !== generation.current) return;
        turn.events.push(event);
        if (event.type === "context") setContext(event.data);
        if (event.type === "answer_delta") turn.answer += event.data.text;
        if (event.type === "completed") turn.state = "completed";
        if (event.type === "failed") turn.state = "failed";
        update();
      }, next.signal);
      if (epoch === generation.current && turn.state === "completed" && turn.answer) {
        history.current = [...history.current, { question: turn.question, answer: turn.answer }].slice(-20);
        while (history.current.reduce((total, item) => total + item.question.length + item.answer.length, 0) > 64000) history.current.shift();
      }
    } catch {
      turn.state = next.signal.aborted ? "stopped" : "failed";
      update();
    } finally {
      if (epoch === generation.current) { controller.current = null; setBusy(false); }
    }
  };

  return { context, turns, busy, loading, error, send, clear, loadContext, stop: () => controller.current?.abort() };
}
