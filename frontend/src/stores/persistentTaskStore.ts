import { useCallback } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { create } from 'zustand'

type StoredValue = unknown

interface PersistentTaskState {
  values: Record<string, StoredValue>
  setValue: (key: string, value: StoredValue) => void
  clearPrefix: (prefix: string) => void
}

const usePersistentTaskStore = create<PersistentTaskState>((set) => ({
  values: {},
  setValue: (key, value) => set(state => ({
    values: { ...state.values, [key]: value },
  })),
  clearPrefix: (prefix) => set(state => ({
    values: Object.fromEntries(
      Object.entries(state.values).filter(([key]) => !key.startsWith(prefix)),
    ),
  })),
}))

export function clearPersistentTaskPrefix(prefix: string) {
  usePersistentTaskStore.getState().clearPrefix(prefix)
}

export function usePersistentTaskValues() {
  return usePersistentTaskStore(state => state.values)
}

/**
 * Keeps in-flight task state in a global in-memory store so navigating between
 * routes does not reset buttons, progress, inputs, or generated results.
 */
export function usePersistentState<T>(key: string, initialValue: T): [T, Dispatch<SetStateAction<T>>] {
  const storedValue = usePersistentTaskStore(state => state.values[key])
  const setValue = usePersistentTaskStore(state => state.setValue)
  const value = (storedValue === undefined ? initialValue : storedValue) as T

  const update = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    const current = usePersistentTaskStore.getState().values[key]
    const previous = (current === undefined ? initialValue : current) as T
    const resolved = typeof next === 'function'
      ? (next as (previousValue: T) => T)(previous)
      : next
    setValue(key, resolved)
  }, [initialValue, key, setValue])

  return [value, update]
}
