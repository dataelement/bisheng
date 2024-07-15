export default function CrashErrorComponent({ error, resetErrorBoundary }) {

  return (
    <div className="fixed left-0 top-0 z-50 flex h-full w-full items-center justify-center bg-background-main">
      <div className="flex min-h-fit max-w-2xl flex-col justify-evenly rounded-lg bg-card p-8 text-start shadow-lg">
        <h1 className="mb-4 text-2xl text-status-red">
          {error.toString()}
        </h1>
        <p className="mb-4 text-lg text-foreground">
          Please click the 'Reset Application' button to restore the application's state.If the error persists, please contact us.We apologize for any inconvenience this may have caused.
        </p>
        <div className="flex justify-center gap-4">
          <a
            href="https://github.com/dataelement/bisheng/issues/new"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded bg-status-red px-4 py-2 font-bold text-primary-foreground hover:bg-status-red/80"
          >
            Create Issue
          </a>
          <button
            onClick={resetErrorBoundary}
            className="mr-4 rounded bg-primary px-4 py-2 font-bold text-sm text-primary-foreground hover:bg-primary/80"
          >
            Reset Application
          </button>
        </div>
      </div>
    </div>
  );
}
