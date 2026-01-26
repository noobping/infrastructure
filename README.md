
# Desktop ignition

Build the butane files:

```sh
yq ea '. as $item ireduce ({}; . *+ $item)' base.yml live.yml > live.bu
yq ea '. as $item ireduce ({}; . *+ $item)' base.yml desktop.yml > desktop.bu
```

Build ignition file:

```sh
butane --pretty --strict desktop.bu > desktop.json
```
