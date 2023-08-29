## Repository for langchain's extra modules

This repository is intended for the development of so-called "extra" modules,
contributed functionality. New modules quite often do not have stable API,
and they are not well-tested. Thus, they shouldn't be released as a part of the
official langchain distribution, since the library maintains binary compatibility,
and tries to provide decent performance and stability.

So, all the new modules should be developed separately, and published in the
`langchain_contrib` repository at first. Later, when the module matures and gains
popularity, it will create a pr for langchain.


### Update the repository documentation

In order to keep a clean overview containing all contributed modules, the following files need to be created/adapted:

1. Update the README.md file under the modules folder. Here, you add your model with a single-line description.

2. Add a README.md inside your own module folder. This README explains which functionality (separate functions) is available, links to the corresponding samples, and explains in somewhat more detail what the module is expected to do. If any extra requirements are needed to build the module without problems, add them here also.
