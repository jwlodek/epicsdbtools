Python Module to Read EPICS Database
====================================

Simply put, this module implements iocsh commands dbLoadRecords and dbLoadTemplate in Python. Each record is represented by a *Record* object and then records are aggregated into a *Database* object.

Usage
-----

::

    from dbtoolspy import load_template_file, load_database_file
    templates = load_template_file('example.subs')

``templates`` is a list of *(dbfile, macros)* tuples. *dbfile* is the database file name and *macros* is a dictionary containing the macro substitution. They are then passed to *load_database_file*.

::

    for dbfile, macros in templates:
        database = load_database_file(dbfile, macros)
        print(database)

``database`` is a *Database* instance. Since *Database* derives from OrderedDict, it can be iterated::

    for record in database.values():
        print(record.name)


Reference
---------

load_template_file takes the following argument:

   subsfile
     Substitution file.

   encoding
     (Optional) File encoding. (default utf-8)


load_database_file takes the following argument:

   dbfile
     Database file.

   macros
     (Optional) Dict of macro substitution. If *None* is given, no macro expansion is performed.

   includes
     (Optional) Extra include paths for database files.

   encoding
     (Optional) File encoding. (default utf-8)

   load_includes
     (Optional) Follow *include* directive. (default True)

Record has the following attibutes:

  name 
    Record name.

  rtyp
    Record type.

  fields
    Dictionary of record fields.

  infos
    Dictionary of record infos.

  aliases
    List of aliased names.


Database derives from OrderedDict. The key is the record name and the value the *Record* instance. Additional methods:

  add_record
    Add a new *Record* instance.

  get_included_templates
    Get template files referenced by all *include* directives.

  update
    Add records from another *Database* instance. If there exists a record with the same *name* and the same *rtyp*, the new *fields*, *infos* and *aliases* 
    attributes will merge with the existing. If *rtyp* is difference, *DatabaseException* will be raised.


Tools
-----

dbiocdiff.py
  It compares the configured field values with the IOC runtime values and reports the difference.


Limitations
-----------

* In the substitution file, the template file name cannot contain macros.
* It is stricter when treating valid characters in bare words. Quote them in case of *TokenException*. 
