import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Machine:
    id: int
    url: str
    location_slug: str
    machine_type: str

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.location_slug, self.machine_type, self.id)


@dataclass(frozen=True)
class MachineGroup:
    slug: str
    label: str
    singular_label: str
    machines: tuple[Machine, ...]


@dataclass(frozen=True)
class Location:
    slug: str
    name: str
    default_machine_type: str
    machine_types: tuple[MachineGroup, ...]

    def group(self, machine_type: str) -> MachineGroup:
        for group in self.machine_types:
            if group.slug == machine_type:
                return group
        raise KeyError(machine_type)


@dataclass(frozen=True)
class Catalog:
    locations: tuple[Location, ...]

    def location(self, location_slug: str) -> Location:
        for location in self.locations:
            if location.slug == location_slug:
                return location
        raise KeyError(location_slug)

    def machines(self) -> tuple[Machine, ...]:
        return tuple(
            machine
            for location in self.locations
            for group in location.machine_types
            for machine in group.machines
        )

    def machine(self, location_slug: str, machine_type: str, machine_id: int) -> Machine:
        group = self.location(location_slug).group(machine_type)
        for machine in group.machines:
            if machine.id == machine_id:
                return machine
        raise KeyError(machine_id)


def load_catalog(path: Path) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    locations = []
    seen_keys = set()

    for raw_location in raw["locations"]:
        location_slug = raw_location["slug"]
        groups = []
        for raw_group in raw_location["machine_types"]:
            machine_type = raw_group["slug"]
            machines = []
            for raw_machine in raw_group["machines"]:
                machine = Machine(
                    id=int(raw_machine["id"]),
                    url=raw_machine["url"],
                    location_slug=location_slug,
                    machine_type=machine_type,
                )
                if machine.key in seen_keys:
                    raise ValueError(f"Duplicate machine entry: {machine.key}")
                seen_keys.add(machine.key)
                machines.append(machine)
            groups.append(
                MachineGroup(
                    slug=machine_type,
                    label=raw_group["label"],
                    singular_label=raw_group["singular_label"],
                    machines=tuple(machines),
                )
            )
        location = Location(
            slug=location_slug,
            name=raw_location["name"],
            default_machine_type=raw_location["default_machine_type"],
            machine_types=tuple(groups),
        )
        location.group(location.default_machine_type)
        locations.append(location)

    if not locations:
        raise ValueError("Machine catalog must include at least one location")
    return Catalog(tuple(locations))
