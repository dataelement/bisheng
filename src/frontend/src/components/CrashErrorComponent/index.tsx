export default function CrashErrorComponent({ error, resetErrorBoundary }) {
  return (
    <div className="fixed left-0 top-0 z-50 flex h-full w-full items-center justify-center bg-foreground bg-opacity-50">
      <div className="flex h-1/4 min-h-fit max-w-2xl flex-col justify-evenly rounded-lg bg-background p-8 text-start shadow-lg">
        <h1 className="mb-4 text-2xl text-status-red">
          未知错误。
        </h1>
        <p className="mb-4 text-lg text-foreground">
          请单击 "重置应用程序 "按钮恢复应用程序的状态。如果错误仍然存在，请联系我们。对于由此造成的不便，我们深表歉意
        </p>
        <div className="flex justify-center">
          <button
            onClick={resetErrorBoundary}
            className="mr-4 rounded bg-primary px-4 py-2 font-bold text-sm text-background hover:bg-ring"
          >
            重置应用程序
          </button>
        </div>
      </div>
    </div>
  );
}
