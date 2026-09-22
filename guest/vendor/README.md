# Vendored dependencies

Ubuntu 24.04 (noble) ships no `gbinder` packages at all, and the PyPI
`gbinder` module is only a Cython wrapper that links against the C library
`libgbinder`. Without the module, `androidbox` cannot even start, because
`tools/actions/__init__.py` imports it at module level (`gbinder` through
`tools.interfaces.IPlatform` and `app_manager`). The guest image is therefore
provisioned by building these projects from their vendored source trees.

`guest/provision.sh` builds them best-effort: if the build fails the boot
continues, but binder integration (clipboard, notifications, hardware
controls, immersive mode) is unavailable and `androidbox` commands that
import `gbinder` fail.

| Directory | Project | Version | License |
| --- | --- | --- | --- |
| `libglibutil/` | sailfishos/libglibutil | 1.0.81 | BSD-3-Clause |
| `libgbinder/` | mer-hybris/libgbinder | 1.1.45 | BSD-3-Clause |
| `python-gbinder/` | erfanoobdi/gbinder-python | 1.3.1 | GPL-3.0 |

Both C libraries come from the Debian source packages (upstream tarballs) and
are built with their plain Makefiles:

```sh
make -C libglibutil release pkgconfig
make -C libglibutil install-dev LIBDIR=usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)
make -C libgbinder release pkgconfig
make -C libgbinder install-dev LIBDIR=usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)
ldconfig
```

`python-gbinder` then builds its Cython extension with
`python3 setup.py build_ext --inplace` (its `setup.py` always cythonizes; the
documented `--cython` flag is not wired up) and copies the resulting
`gbinder*.so` into `/usr/local/lib/python3.12/dist-packages/`.

Refresh the vendored trees from the Debian source packages (`apt-get source`
with `deb-src` enabled) and keep them pristine so updates stay a mechanical
copy of the upstream tarball.
