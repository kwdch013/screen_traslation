import { useCallback, useEffect, useReducer, useRef } from 'react'

import type { SubtitleEntry, TranslationResult } from './translationEvents'
import { parseTranslationResult, parseTranslationState } from './translationEvents'

export const RESULT_TTL_MS = 10_000
export const SUBTITLE_HISTORY_LIMIT = 100

type ConnectionState = 'connecting' | 'connected' | 'reconnecting'

interface EventState {
	connection: ConnectionState
	generation: number | null
	latestFrameId: number
	currentResult: TranslationResult | null
	history: SubtitleEntry[]
	blockedUntilGenerationChange: boolean
}

type EventAction =
	| { type: 'connected' }
	| { type: 'disconnected' }
	| { type: 'state'; generation: number }
	| { type: 'result'; result: TranslationResult }
	| { type: 'expire'; generation: number; frameId: number }
	| { type: 'clearForSessionChange' }

const initialState: EventState = {
	connection: 'connecting',
	generation: null,
	latestFrameId: -1,
	currentResult: null,
	history: [],
	blockedUntilGenerationChange: false,
}

export function useTranslationEvents() {
	const [state, dispatch] = useReducer(eventReducer, initialState)
	const ttlTimerRef = useRef<number | null>(null)

	const clearTtl = useCallback(() => {
		if (ttlTimerRef.current !== null) {
			window.clearTimeout(ttlTimerRef.current)
			ttlTimerRef.current = null
		}
	}, [])

	const clearForSessionChange = useCallback(() => {
		clearTtl()
		dispatch({ type: 'clearForSessionChange' })
	}, [clearTtl])

	useEffect(() => {
		const eventSource = new EventSource('/api/events')
		eventSource.onopen = () => dispatch({ type: 'connected' })
		eventSource.onerror = () => dispatch({ type: 'disconnected' })
		eventSource.addEventListener('state', (event) => {
			if (!(event instanceof MessageEvent)) return
			const status = parseTranslationState(event.data)
			if (!status) return
			dispatch({ type: 'state', generation: status.generation })
		})
		eventSource.addEventListener('translation_result', (event) => {
			if (!(event instanceof MessageEvent)) return
			const result = parseTranslationResult(event.data)
			if (!result) return
			dispatch({ type: 'result', result })
		})
		return () => {
			clearTtl()
			eventSource.close()
		}
	}, [clearTtl])

	useEffect(() => {
		clearTtl()
		const result = state.currentResult
		if (!result) return
		ttlTimerRef.current = window.setTimeout(() => {
			dispatch({ type: 'expire', generation: result.generation, frameId: result.frame_id })
		}, RESULT_TTL_MS)
		return clearTtl
	}, [clearTtl, state.currentResult])

	return {
		connection: state.connection,
		currentResult: state.currentResult,
		history: state.history,
		clearForSessionChange,
	}
}

function eventReducer(state: EventState, action: EventAction): EventState {
	switch (action.type) {
		case 'connected':
			return { ...state, connection: 'connected' }
		case 'disconnected':
			return { ...state, connection: 'reconnecting' }
		case 'clearForSessionChange':
			return {
				...state,
				currentResult: null,
				history: [],
				blockedUntilGenerationChange: true,
			}
		case 'state':
			if (state.generation !== null && action.generation <= state.generation) return state
			return resetGeneration(state, action.generation)
		case 'result':
			return applyResult(state, action.result)
		case 'expire':
			if (
				state.currentResult?.generation !== action.generation
				|| state.currentResult.frame_id !== action.frameId
			) return state
			return { ...state, currentResult: null }
	}
}

function resetGeneration(state: EventState, generation: number): EventState {
	return {
		...state,
		generation,
		latestFrameId: -1,
		currentResult: null,
		history: [],
		blockedUntilGenerationChange: false,
	}
}

function applyResult(state: EventState, result: TranslationResult): EventState {
	if (state.generation !== null && result.generation < state.generation) return state
	const generationState = state.generation === result.generation
		? state
		: resetGeneration(state, result.generation)
	if (generationState.blockedUntilGenerationChange || result.frame_id <= generationState.latestFrameId) {
		return generationState
	}
	const additions = result.regions.map((region, index) => ({
		...region,
		id: `${result.generation}-${result.frame_id}-${index}`,
		generation: result.generation,
		frameId: result.frame_id,
	}))
	return {
		...generationState,
		latestFrameId: result.frame_id,
		currentResult: result.regions.length > 0 ? result : null,
		history: additions.length > 0
			? [...additions, ...generationState.history].slice(0, SUBTITLE_HISTORY_LIMIT)
			: generationState.history,
	}
}
