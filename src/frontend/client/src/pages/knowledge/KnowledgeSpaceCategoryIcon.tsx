import cn from '~/utils/cn';
import { knowledgeSpaceIcons } from './knowledgeSpaceIcons';

interface KnowledgeSpaceCategoryIconProps {
  source: keyof typeof knowledgeSpaceIcons;
  size: number;
  className?: string;
}

/** Follow the app's resolved .dark class, including manual and system theme changes. */
export function KnowledgeSpaceCategoryIcon({ source, size, className }: KnowledgeSpaceCategoryIconProps) {
  const icons = knowledgeSpaceIcons[source];
  return (
    <>
      <img src={icons.light} className={cn(className, 'dark:hidden')} width={size} height={size} alt="" />
      <img src={icons.dark} className={cn(className, 'hidden dark:block')} width={size} height={size} alt="" />
    </>
  );
}
