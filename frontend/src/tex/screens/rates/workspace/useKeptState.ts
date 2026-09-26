// The React side of the kept workspace input (keptState.ts): the editor's store as a context, and
// useKeptState, a useState whose value outlives the component in that store (S16 review).
import { createContext, useCallback, useContext, useState, type SetStateAction } from "react"
import type { KeptStore } from "./keptState.ts"

export const KeptStateContext = createContext<KeptStore | null>(null)

export function useKeptStore(): KeptStore | null {
  return useContext(KeptStateContext)
}

/**
 * useState whose value outlives the component in the editor's store under `key` (without a store:
 * plain useState). The third value says whether it was taken back from the store.
 */
export function useKeptState<T>(key: string, initial: T | (() => T)): [T, (next: SetStateAction<T>) => void, boolean] {
  const store = useKeptStore()
  const [restored] = useState(() => Boolean(store?.has(key)))
  const [value, setValue] = useState<T>(() => (store?.has(key) ? (store.get(key) as T) : typeof initial === "function" ? (initial as () => T)() : initial))
  const set = useCallback(
    (next: SetStateAction<T>) =>
      setValue((prev) => {
        const v = typeof next === "function" ? (next as (p: T) => T)(prev) : next
        store?.set(key, v)
        return v
      }),
    [store, key],
  )
  return [value, set, restored]
}

