import { useCallback, useEffect, useMemo, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import type { DatesSetArg, EventClickArg, EventInput } from '@fullcalendar/core'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import listPlugin from '@fullcalendar/list'
import { api } from '../api/client'
import type { EnumCatalog, Task } from '../api/types'
import { FilterBar } from '../filters/FilterBar'
import { toQuery, useFacets, useFilters } from '../filters/filters'
import { TaskDetail } from '../tasks/TaskDetail'

/**
 * Every committed task with a due date, overlaid on a month / week / agenda
 * calendar. FullCalendar owns all the date maths — the only dates this file
 * handles are the ISO strings the API already speaks.
 */

/** Criticality drives colour: the calendar should answer "what could hurt?". */
const CRITICALITY_COLOR: Record<string, string> = {
  critical: '#c0392b',
  high: '#d97706',
  medium: '#2f6feb',
  low: '#6b7280',
}
const UNSET_COLOR = '#9aa3ae'

export function CalendarView({
  enums,
  revision,
}: {
  enums: EnumCatalog
  revision: number
}) {
  const { filters, set, toggle, reset } = useFilters()
  const facets = useFacets(revision)
  const [tasks, setTasks] = useState<Task[]>([])
  const [range, setRange] = useState<{ start: string; end: string } | null>(null)
  const [selected, setSelected] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (start: string, end: string) => {
      try {
        // Fetch only the visible window; the server filters by due date.
        setTasks(await api.listTasks(toQuery(filters, { due_from: start, due_to: end })))
        setError(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    [filters],
  )

  // Refetch whenever the visible window, the filters, or the committed data
  // change. `range` is compared by value in onDatesSet so paging to the same
  // window does not loop.
  useEffect(() => {
    if (range) void load(range.start, range.end)
  }, [range, load, revision])

  const events: EventInput[] = useMemo(
    () =>
      tasks
        .filter((t) => t.due_date)
        .map((t) => ({
          id: t.id,
          title: t.title,
          start: t.due_date!,
          allDay: true,
          backgroundColor: CRITICALITY_COLOR[t.criticality ?? ''] ?? UNSET_COLOR,
          borderColor: CRITICALITY_COLOR[t.criticality ?? ''] ?? UNSET_COLOR,
          // Done work stays visible but recedes.
          classNames: t.status === 'done' ? ['fc-task-done'] : [],
          extendedProps: { task: t },
        })),
    [tasks],
  )

  function onEventClick(arg: EventClickArg) {
    setSelected(arg.event.extendedProps.task as Task)
  }

  function onDatesSet(arg: DatesSetArg) {
    const start = arg.startStr.slice(0, 10)
    const end = arg.endStr.slice(0, 10)
    setRange((prev) => (prev?.start === start && prev.end === end ? prev : { start, end }))
  }

  return (
    <div className="stack">
      <FilterBar
        filters={filters}
        facets={facets}
        enums={enums}
        onSet={set}
        onToggle={toggle}
        onReset={reset}
      />

      {error && <div className="panel error">{error}</div>}

      <div className="panel">
        <div className="legend">
          {Object.entries(CRITICALITY_COLOR).map(([level, color]) => (
            <span key={level}>
              <i style={{ background: color }} /> {level}
            </span>
          ))}
          <span>
            <i style={{ background: UNSET_COLOR }} /> criticality unset
          </span>
          <span className="spacer" />
          <span className="env">
            {events.length} of {tasks.length} shown — tasks with no due date are not on the
            calendar
          </span>
        </div>

        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin, listPlugin]}
          initialView="dayGridMonth"
          headerToolbar={{
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,listMonth',
          }}
          buttonText={{ today: 'Today', month: 'Month', week: 'Week', list: 'Agenda' }}
          height="auto"
          firstDay={1}
          events={events}
          eventClick={onEventClick}
          datesSet={onDatesSet}
          noEventsText="Nothing due in this range"
        />
      </div>

      {selected && <TaskDetail task={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
