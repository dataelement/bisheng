import { LoadingState } from "@/components/bs-icons/loading/LoadingState"
import { Suspense, lazy } from "react"

const Departments = lazy(() => import("./Departments"))

export default function OrganizationAndMembers() {
  return (
    <Suspense
      fallback={
        <LoadingState size="page" className="h-40" />
      }
    >
      <Departments />
    </Suspense>
  )
}
