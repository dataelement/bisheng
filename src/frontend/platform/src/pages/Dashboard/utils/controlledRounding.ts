// Display rounding for a share-of-total pivot. Each knowledge sits in one cell, so the
// unrounded column total already equals the sum of that column. Showing every figure to
// one decimal independently makes those sums disagree by 0.1 percentage points.
// Controlled rounding keeps each cell on one side of its true value, at most one display
// unit away, and makes the rounded rows, columns, and grand total add up.

// Float noise from ratio * scale, far below one display unit.
const UNIT_EPSILON = 1e-4

export interface ShareTable {
  cells: number[][]
  rowTotals: number[]
  columnTotals: number[]
  grandTotal: number
}

function scaleFor(decimalPlaces: number): number {
  const places = Math.min(Math.max(decimalPlaces, 0), 5)
  return 10 ** (places + 2)
}

function toUnits(ratio: number, scale: number): number {
  const scaled = ratio * scale
  const nearest = Math.round(scaled)
  return Math.abs(scaled - nearest) < UNIT_EPSILON ? nearest : scaled
}

function floorUnits(value: number): number {
  return Math.floor(value + UNIT_EPSILON)
}

function sumsMatch(actual: number, expected: number): boolean {
  return Math.abs(actual - expected) < 1e-4
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0)
}

function partitions(table: ShareTable, scale: number): boolean {
  const cells = table.cells.map(row => row.map(value => toUnits(value, scale)))
  const rowTotals = table.rowTotals.map(value => toUnits(value, scale))
  const columnTotals = table.columnTotals.map(value => toUnits(value, scale))
  const grand = toUnits(table.grandTotal, scale)
  if (!sumsMatch(sum(rowTotals), grand) || !sumsMatch(sum(columnTotals), grand)) return false
  if (cells.length !== rowTotals.length) return false
  if (cells.some(row => row.length !== columnTotals.length)) return false
  for (let row = 0; row < cells.length; row++) {
    if (!sumsMatch(sum(cells[row]), rowTotals[row])) return false
  }
  for (let column = 0; column < columnTotals.length; column++) {
    const columnSum = cells.reduce((total, row) => total + row[column], 0)
    if (!sumsMatch(columnSum, columnTotals[column])) return false
  }
  return cells.every(row => row.every(value => value >= -UNIT_EPSILON))
}

// Largest remainder. The parts sum to target. A normal 100% split moves each part by at most one unit.
function apportion(exact: number[], target: number): number[] {
  const base = exact.map(value => floorUnits(value))
  const fraction = exact.map((value, index) => value - base[index])
  let leftover = target - sum(base)
  const indexes = exact.map((_, index) => index)
  let guard = 0
  while (leftover !== 0 && guard++ < exact.length * 4 + Math.abs(leftover)) {
    if (leftover > 0) {
      indexes.sort((left, right) => fraction[right] - fraction[left] || left - right)
      const index = indexes[0]
      base[index] += 1
      fraction[index] -= 1
      leftover -= 1
      continue
    }
    indexes.sort((left, right) => fraction[left] - fraction[right] || left - right)
    const index = indexes.find(item => base[item] > 0)
    if (index === undefined) break
    base[index] -= 1
    fraction[index] += 1
    leftover += 1
  }
  return base
}

function assignIncrements(
  eligible: boolean[][],
  preference: number[][],
  rowNeed: number[],
  columnNeed: number[],
): boolean[][] | null {
  const rowCount = rowNeed.length
  const columnCount = columnNeed.length
  const taken = Array.from({ length: rowCount }, () => Array(columnCount).fill(false))
  const rowLeft = rowNeed.slice()
  const columnLeft = columnNeed.slice()
  const candidates: { row: number, column: number, fraction: number }[] = []
  for (let row = 0; row < rowCount; row++) {
    for (let column = 0; column < columnCount; column++) {
      if (eligible[row][column]) candidates.push({ row, column, fraction: preference[row][column] })
    }
  }
  candidates.sort((left, right) => right.fraction - left.fraction || left.row - right.row || left.column - right.column)
  for (const candidate of candidates) {
    if (rowLeft[candidate.row] > 0 && columnLeft[candidate.column] > 0) {
      taken[candidate.row][candidate.column] = true
      rowLeft[candidate.row] -= 1
      columnLeft[candidate.column] -= 1
    }
  }

  const augment = (): boolean => {
    const parentColumnOfRow = Array(rowCount).fill(-1)
    const parentRowOfColumn = Array(columnCount).fill(-1)
    const queue: number[] = []
    for (let row = 0; row < rowCount; row++) {
      if (rowLeft[row] > 0) {
        parentColumnOfRow[row] = -2
        queue.push(row)
      }
    }
    let sinkColumn = -1
    for (let head = 0; head < queue.length && sinkColumn < 0; head++) {
      const row = queue[head]
      for (let column = 0; column < columnCount; column++) {
        if (!eligible[row][column] || taken[row][column] || parentRowOfColumn[column] !== -1) continue
        parentRowOfColumn[column] = row
        if (columnLeft[column] > 0) {
          sinkColumn = column
          break
        }
        for (let other = 0; other < rowCount; other++) {
          if (taken[other][column] && parentColumnOfRow[other] === -1) {
            parentColumnOfRow[other] = column
            queue.push(other)
          }
        }
      }
    }
    if (sinkColumn < 0) return false
    let column = sinkColumn
    let startRow = -1
    while (true) {
      const row = parentRowOfColumn[column]
      taken[row][column] = true
      const previous = parentColumnOfRow[row]
      if (previous === -2) {
        startRow = row
        break
      }
      taken[row][previous] = false
      column = previous
    }
    rowLeft[startRow] -= 1
    columnLeft[sinkColumn] -= 1
    return true
  }

  while (sum(rowLeft) > 0) {
    if (!augment()) return null
  }
  return taken
}

function fromUnits(cells: number[][], scale: number): ShareTable {
  const rowTotals = cells.map(row => sum(row))
  const columnTotals = cells[0].map((_, column) => cells.reduce((total, row) => total + row[column], 0))
  return {
    cells: cells.map(row => row.map(units => units / scale)),
    rowTotals: rowTotals.map(units => units / scale),
    columnTotals: columnTotals.map(units => units / scale),
    grandTotal: sum(rowTotals) / scale,
  }
}

// The footer is what readers add up. Snap it to the rounded grand total even when a cell
// is slightly off its rollup, then move that same 0.1 into the cell with the largest fraction.
function lockFooter(table: ShareTable, scale: number): ShareTable | null {
  const grandExact = toUnits(table.grandTotal, scale)
  const grandTarget = Math.round(grandExact)
  const columnExact = table.columnTotals.map(value => toUnits(value, scale))
  if (Math.abs(sum(columnExact) - grandExact) > 1 + UNIT_EPSILON) return null
  const columnTargets = apportion(columnExact, grandTarget)
  if (sum(columnTargets) !== grandTarget) return null

  const exactCells = table.cells.map(row => row.map(value => toUnits(value, scale)))
  const structuralZero = exactCells.map(row => row.map(value => value <= UNIT_EPSILON))
  const fractions = exactCells.map(row => row.map(value => value - floorUnits(value)))
  const rounded = exactCells.map((row, rowIndex) => row.map((value, columnIndex) => (
    structuralZero[rowIndex][columnIndex] ? 0 : Math.round(value)
  )))

  for (let column = 0; column < columnTargets.length; column++) {
    let need = columnTargets[column] - rounded.reduce((total, row) => total + row[column], 0)
    let guard = 0
    while (need !== 0 && guard++ < rounded.length * 4 + Math.abs(need)) {
      const step = need > 0 ? 1 : -1
      let best = -1
      let bestScore = step > 0 ? -Infinity : Infinity
      for (let row = 0; row < rounded.length; row++) {
        if (structuralZero[row][column]) continue
        if (step < 0 && rounded[row][column] + step < 0) continue
        const score = fractions[row][column]
        const better = step > 0 ? score > bestScore : score < bestScore
        if (better) {
          best = row
          bestScore = score
        }
      }
      if (best < 0) break
      rounded[best][column] += step
      fractions[best][column] -= step
      need -= step
    }
  }
  return fromUnits(rounded, scale)
}

export function reconcileShareRatios(table: ShareTable, decimalPlaces: number): ShareTable | null {
  if (table.cells.length === 0 || table.cells[0].length === 0) return null
  const scale = scaleFor(decimalPlaces)
  if (!partitions(table, scale)) return lockFooter(table, scale)

  const cells = table.cells.map(row => row.map(value => toUnits(value, scale)))
  const grand = Math.round(toUnits(table.grandTotal, scale))
  const rowTargets = apportion(table.rowTotals.map(value => toUnits(value, scale)), grand)
  const columnTargets = apportion(table.columnTotals.map(value => toUnits(value, scale)), grand)
  if (sum(rowTargets) !== grand || sum(columnTargets) !== grand) return lockFooter(table, scale)

  const floors = cells.map(row => row.map(value => floorUnits(value)))
  const eligible = cells.map((row, rowIndex) => row.map((value, columnIndex) => value - floors[rowIndex][columnIndex] > UNIT_EPSILON))
  const fractions = cells.map((row, rowIndex) => row.map((value, columnIndex) => value - floors[rowIndex][columnIndex]))
  const rowNeed = rowTargets.map((target, row) => target - sum(floors[row]))
  const columnNeed = columnTargets.map((target, column) => target - floors.reduce((total, row) => total + row[column], 0))
  if (rowNeed.some(need => need < 0) || columnNeed.some(need => need < 0)) return lockFooter(table, scale)

  const increments = assignIncrements(eligible, fractions, rowNeed, columnNeed)
  if (!increments) return lockFooter(table, scale)

  const rounded = floors.map((row, rowIndex) => row.map((value, columnIndex) => value + (increments[rowIndex][columnIndex] ? 1 : 0)))
  return {
    cells: rounded.map(row => row.map(units => units / scale)),
    rowTotals: rowTargets.map(units => units / scale),
    columnTotals: columnTargets.map(units => units / scale),
    grandTotal: grand / scale,
  }
}
