import { Link } from 'react-router-dom'

interface ItemLike {
  id: number | null
  name: string | null
  slug?: string
  icon_url: string | null
}

/**
 * An item's icon, linking to its page in the item guide.
 *
 * The one place an item is drawn, so every scoreboard, match row and build on
 * the site leads to the item it shows. The name is the link's accessible label
 * and its tooltip, because an icon alone says nothing to a screen reader.
 * An empty slot stays an empty box and links nowhere.
 */
export default function ItemIcon({
  item,
  size,
  className = '',
  search = '',
}: {
  item: ItemLike | null
  /** Pixels. */
  size: number
  /** The box's own look (radius, background), which differs by place. */
  className?: string
  /** A query string for the item page, e.g. the patch and queue being read. */
  search?: string
}) {
  const box = `block shrink-0 overflow-hidden ${className}`
  const style = { width: size, height: size }
  if (!item?.id || !item.icon_url) {
    return <span className={box} style={style} aria-hidden />
  }
  return (
    <Link
      to={`/items/${item.slug ?? item.id}${search}`}
      title={item.name ?? undefined}
      aria-label={item.name ?? `Item ${item.id}`}
      className={`${box} outline-offset-1 transition-[filter] hover:brightness-125 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-bright`}
      style={style}
    >
      <img src={item.icon_url} alt="" loading="lazy" className="size-full" />
    </Link>
  )
}
