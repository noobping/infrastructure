# NAS

Create `/var/lib/containers/secrets/admin-password` before expecting the Uptime Kuma bootstrap to finish.

You can also set `/var/lib/containers/secrets/admin-username`; it defaults to `admin`.

This image no longer provisions FreeIPA, FreeRADIUS, or any other domain-controller services.
