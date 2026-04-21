import { Skeleton } from '~/components/ui';

export default function SkeletonForm() {
  return (
    <div>
      <div className="flex flex-col items-center justify-between px-4 dark:text-gray-200 sm:flex-row">
        <Skeleton className="mb-1 flex h-10 w-32 flex-row items-center font-bold sm:text-xl touch-desktop:mb-0 touch-desktop:h-12 touch-desktop:text-2xl" />
      </div>
      <div className="flex h-full w-full flex-col touch-desktop:flex-row">
        {/* Left Section */}
        <div className="flex-1 overflow-y-auto border-border-medium-alt p-4 touch-desktop:max-h-[calc(100vh-150px)] touch-desktop:border-r">
          <Skeleton className="h-96" />
        </div>
      </div>
    </div>
  );
}
