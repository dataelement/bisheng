import cloneDeep from "lodash-es/cloneDeep";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { Edge, Node, useReactFlow } from "@xyflow/react";
import { TabsContext } from "./tabsContext";

type undoRedoContextType = {
  undo: () => void;
  redo: () => void;
  takeSnapshot: () => void;
};

type UseUndoRedoOptions = {
  maxHistorySize: number;
  enableShortcuts: boolean;
};

type UseUndoRedo = (options?: UseUndoRedoOptions) => {
  undo: () => void;
  redo: () => void;
  takeSnapshot: () => void;
  canUndo: boolean;
  canRedo: boolean;
};

type HistoryItem = {
  nodes: Node[];
  edges: Edge[];
};

const initialValue = {
  undo: () => { },
  redo: () => { },
  takeSnapshot: () => { },
};

const defaultOptions: UseUndoRedoOptions = {
  maxHistorySize: 100,
  enableShortcuts: true,
};

export const undoRedoContext = createContext<undoRedoContextType>(initialValue);

export function UndoRedoProvider({ children }) {
  const { flow } = useContext(TabsContext);

  const [past, setPast] = useState<HistoryItem[]>([]);
  const [future, setFuture] = useState<HistoryItem[]>([]);

  useEffect(() => {
    // whenever the flows variable changes, we need to add one array to the past and future states
    setPast([]);
    setFuture([]);
  }, [flow?.id]);

  // 通过getNodes, getEdges读取状态写入队列，通过setNodes, setEdges还原
  const { setNodes, setEdges, getNodes, getEdges } = useReactFlow();

  const takeSnapshot = useCallback(() => {
    // push the current graph to the past state
    setPast((old) => {
      let newPast = cloneDeep(old);
      newPast = old.slice(
        old.length - defaultOptions.maxHistorySize + 1,
        old.length
      );
      newPast.push({ nodes: getNodes(), edges: getEdges() });
      return newPast;
    });

    // whenever we take a new snapshot, the redo operations need to be cleared to avoid state mismatches
    setFuture([]);
  }, [getNodes, getEdges, past, future, flow, setPast, setFuture]);

  const undo = useCallback(() => {
    // get the last state that we want to go back to
    const pastState = past[past.length - 1];

    if (pastState) {
      // first we remove the state from the history
      setPast((old) => {
        let newPast = cloneDeep(old);
        newPast = old.slice(0, old.length - 1);
        return newPast;
      });
      // we store the current graph for the redo operation
      setFuture((old) => {
        let newFuture = cloneDeep(old);
        newFuture = old;
        newFuture.push({ nodes: getNodes(), edges: getEdges() });
        return newFuture;
      });
      // keep same id 
      pastState.nodes.forEach(el => {
        el.data.id = el.id
      })
      // now we can set the graph to the past state
      setNodes(pastState.nodes);
      setEdges(pastState.edges);
    }
  }, [
    setNodes,
    setEdges,
    getNodes,
    getEdges,
    future,
    past,
    setFuture,
    setPast
  ]);

  const redo = useCallback(() => {
    const futureState = future[future.length - 1];

    if (futureState) {
      setFuture((old) => {
        let newFuture = cloneDeep(old);
        newFuture = old.slice(0, old.length - 1);
        return newFuture;
      });
      setPast((old) => {
        let newPast = cloneDeep(old);
        newPast.push({ nodes: getNodes(), edges: getEdges() });
        return newPast;
      });
      // keep same id 
      futureState.nodes.forEach(el => {
        el.data.id = el.id
      })
      setNodes(futureState.nodes);
      setEdges(futureState.edges);
    }
  }, [
    future,
    past,
    setFuture,
    setPast,
    setNodes,
    setEdges,
    getNodes,
    getEdges,
    future
  ]);

  useEffect(() => {
    // this effect is used to attach the global event handlers
    if (!defaultOptions.enableShortcuts) {
      return;
    }

    const keyDownHandler = (event: KeyboardEvent) => {
      if (
        event.key === "z" &&
        (event.ctrlKey || event.metaKey) &&
        event.shiftKey
      ) {
        redo();
      } else if (event.key === "y" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault(); // prevent the default action
        redo();
      } else if (event.key === "z" && (event.ctrlKey || event.metaKey)) {
        undo();
      }
    };

    document.addEventListener("keydown", keyDownHandler);

    return () => {
      document.removeEventListener("keydown", keyDownHandler);
    };
  }, [undo, redo]);
  return (
    <undoRedoContext.Provider
      value={{
        undo,
        redo,
        takeSnapshot,
      }}
    >
      {children}
    </undoRedoContext.Provider>
  );
}
