import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface ErrorBoundaryProps {
  children: ReactNode
  /** Optional fallback component. Receives error and reset function. */
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Catches render-time errors in any descendant and displays a recovery UI.
 * Place around sections of the app that should fail independently.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack)
  }

  reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset)
    }

    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-error-bg bg-surface-overlay text-error">
          <AlertTriangle size={20} />
        </div>
        <strong className="text-base font-semibold text-text-primary">Something went wrong</strong>
        <p className="max-w-xs text-sm text-text-muted">
          {error.message || 'An unexpected error occurred in this component.'}
        </p>
        <button
          onClick={this.reset}
          className="mt-1 flex h-7 items-center gap-1.5 rounded-md bg-surface-active px-3 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-muted hover:text-text-primary"
        >
          <RefreshCw size={12} />
          Try again
        </button>
      </div>
    )
  }
}
