import { Suspense, lazy } from "react"

const Departments = lazy(() => import("./Departments"))

export default function OrganizationAndMembers() {
  return (
    <Suspense
      fallback={
        <div className="flex h-40 items-center justify-center text-muted-foreground">
          Loading...
        </div>
      }
    >
      <Departments />
    </Suspense>
  )
}
