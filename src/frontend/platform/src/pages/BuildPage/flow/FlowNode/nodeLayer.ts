// Above every node (selected nodes sit at 1000) and the edge labels (1001).
const RAISED_Z_INDEX = '2000'

/**
 * Lift the canvas node that contains `el` above its neighbours. Each node wrapper
 * carries its own z-index, so a popup inside a node cannot rise above the node
 * painted after it. Returns the undo; it leaves the value alone if the canvas
 * changed it meanwhile (selection does).
 */
export function raiseNodeLayer(el: Element | null): () => void {
    const node = el?.closest<HTMLElement>('.react-flow__node')
    if (!node) return () => { }
    const previous = node.style.zIndex
    node.style.zIndex = RAISED_Z_INDEX
    return () => {
        if (node.style.zIndex === RAISED_Z_INDEX) node.style.zIndex = previous
    }
}
