# Source files

Drop real source downloads here before running an ingest. Nothing in this
directory is read automatically — an adapter names its own input paths.

```
data/
  adapters/
    nsta/
      wells_2026.csv
      well_reports/
    bgs/
      geoindex_export.csv
    desnz/
      quarterly_prices.csv
  samples/          schema examples only, never loaded
```

A word on keeping raw files here rather than in the container: the licence on
most of these sources restricts redistribution, and a file that lives in a
version-controlled repository is a file that has been redistributed. Add
`data/adapters/**` to `.gitignore` before you put anything real in it.

`data/README.json` documents the schema the sample files follow.