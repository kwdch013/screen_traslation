import { vi } from 'vitest'

export class MockEventSource {
	static instances: MockEventSource[] = []

	readonly url: string | URL
	readonly close = vi.fn()
	private readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>()
	onopen: ((event: Event) => void) | null = null
	onerror: ((event: Event) => void) | null = null

	constructor(url: string | URL) {
		this.url = url
		MockEventSource.instances.push(this)
	}

	addEventListener(type: string, listener: EventListener): void {
		const listeners = this.listeners.get(type) ?? []
		listeners.push(listener as (event: MessageEvent) => void)
		this.listeners.set(type, listeners)
	}

	emitOpen(): void {
		this.onopen?.(new Event('open'))
	}

	emitError(): void {
		this.onerror?.(new Event('error'))
	}

	emitJson(type: 'state' | 'translation_result', data: object): void {
		const event = new MessageEvent(type, { data: JSON.stringify(data) })
		this.listeners.get(type)?.forEach((listener) => listener(event))
	}
}

export function installEventSourceMock(): void {
	MockEventSource.instances = []
	vi.stubGlobal('EventSource', MockEventSource)
}

export function currentEventSource(): MockEventSource {
	const instance = MockEventSource.instances.at(-1)
	if (!instance) throw new Error('EventSourceが作成されていません')
	return instance
}
