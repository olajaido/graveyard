import type { SortDir, SortKey } from '@/lib/model/route';

/** A sortable column header: a `<button>` in a `<th scope="col">` that carries `aria-sort` (ui-core UI-TBL-2). */
export function SortHeader({
  label,
  column,
  sort,
  dir,
  onSort,
}: {
  label: string;
  column: SortKey;
  sort: SortKey;
  dir: SortDir;
  onSort: (column: SortKey) => void;
}) {
  const active = sort === column;
  return (
    <th
      scope="col"
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="px-5 py-3 text-left font-semibold"
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className="inline-flex min-h-6 cursor-pointer items-center gap-1 border-0 bg-transparent p-0 font-[inherit] font-semibold text-inherit"
      >
        {label}
        <span aria-hidden="true">{active ? (dir === 'asc' ? '↑' : '↓') : ''}</span>
      </button>
    </th>
  );
}
