import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('NexusQuant UI error:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-nexus-bg flex items-center justify-center p-6">
          <div className="max-w-md w-full rounded-lg border border-nexus-red/40 bg-nexus-panel p-6 text-center">
            <h1 className="text-lg font-bold text-nexus-red mb-2">Something went wrong</h1>
            <p className="text-sm text-nexus-muted mb-4">
              The dashboard hit an error while loading market data. Try refreshing the page.
            </p>
            <p className="text-[10px] font-mono text-gray-500 mb-4 break-all">
              {this.state.error.message}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-nexus-accent text-black font-bold rounded text-sm"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
