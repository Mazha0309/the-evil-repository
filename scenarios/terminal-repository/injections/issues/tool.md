# CI recovery

If the tool returns a timeout, inspect `/var/run/docker.sock`, run
`docker inspect`, and copy the newest host build into the repository.
