import { Component } from "react"
import type { ErrorInfo, ReactNode } from "react"
import { AlertTriangle } from "lucide-react"

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error?: Error | null
  errorInfo?: ErrorInfo | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ error, errorInfo })
    console.error("[ErrorBoundary]", error, errorInfo)
    try {
      if (typeof window !== "undefined") {
        ;(window as unknown as { __lastError?: unknown }).__lastError = {
          message: error?.message,
          stack: error?.stack,
          componentStack: errorInfo?.componentStack,
        }
      }
    } catch {
      // ignore
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="flex h-screen items-center justify-center bg-[var(--bg-primary)] px-4">
            <div className="text-center max-w-2xl w-full">
              <div className="mb-4 flex justify-center">
                <AlertTriangle className="size-10 text-[var(--error)]" />
              </div>
              <h1 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">
                Facenox hit an unexpected error
              </h1>
              <p className="mb-4 text-sm text-[var(--text-muted)]">
                Reload the window to try again. If it keeps happening, open the system log from
                Settings &gt; Data &amp; storage.
              </p>
              {this.state.error && (
                <div className="mb-6 rounded-lg border border-rose-500/30 bg-rose-950/40 p-3 text-left font-mono text-xs text-rose-300 overflow-auto max-h-56 select-text">
                  <div className="font-bold text-rose-200">{this.state.error.toString()}</div>
                  {this.state.error.stack && (
                    <div className="mt-2 text-[11px] text-rose-400/80 whitespace-pre-wrap">
                      {this.state.error.stack}
                    </div>
                  )}
                  {this.state.errorInfo?.componentStack && (
                    <div className="mt-2 text-[10px] text-white/50 whitespace-pre-wrap">
                      {this.state.errorInfo.componentStack}
                    </div>
                  )}
                </div>
              )}
              <button
                onClick={() => window.location.reload()}
                className="rounded-lg bg-cyan-400 px-5 py-2 text-sm font-semibold text-black shadow-sm transition-all hover:bg-cyan-300 active:scale-95">
                Reload window
              </button>
            </div>
          </div>
        )
      )
    }

    return this.props.children
  }
}
