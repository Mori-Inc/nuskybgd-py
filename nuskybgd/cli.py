"""
Functions to handle using nuskybgd tasks from the command line. These
functions can also be used in Python, either in an interactive session or in a
script, by passing an arguments list to them in lieu of sys.argv.
"""
from . import conf

def run(args=[]):
    """
    Run nuskybgd tasks.

    Usage: nuskybgd task [arguments for task]

    Without task arguments, the usage message for that task will be printed.
    The following tasks are available:
    """
    tasks = {
        'absrmf': absrmf,
        'fitab': fitab,
        'projobs': projobs
    }

    if len(args) == 1:
        print(run.__doc__)
        print('\n'.join(list('        %s' % _ for _ in sorted(tasks.keys()))))
        return 0

    if args[1] in tasks:
        return tasks[args[1]](args[1:])


def absrmf(args=[]):
    """
    Create RMF files that includes detector absorption (DETABS).

    Usage:

    absrmf evtfile outfile [rmffile=CALDB] [detabsfile=CALDB]

    evtfile is an event file from which the INSTRUME and DATE-OBS keywords are
    used.

    outfile will be prefixed to the output file names, and can be a file path.

    rmffile is the RMF file to multiply by absorption, set it to CALDB
    (default) to use the latest CALDB file(s).

    detabsfile is the detector absorption file to multiply the RMF with, set
    it to CALDB (default) to use the latest CALDB file(s).
    """
    if conf.block() is True:
        return 1

    import os
    from . import rmf

    if len(args) not in (3, 4, 5):
        print(absrmf.__doc__)
        return 0

    evtfile = args[1]
    outfile = args[2]

    keywords = {
        'rmffile': 'CALDB',
        'detabsfile': 'CALDB'
    }

    for _ in args[3:]:
        arg = _.split('=')
        if arg[0] in keywords:
            keywords[arg[0]] = arg[1]

    # File exist checks
    halt = False
    if not os.path.exists(evtfile):
        print('%s not found.' % evtfile)
        halt = True
    if (keywords['rmffile'] != 'CALDB' and
            not os.path.exists(keywords['rmffile'])):
        print('%s not found.' % keywords['rmffile'])
        halt = True
    if (keywords['detabsfile'] != 'CALDB' and
            not os.path.exists(keywords['detabsfile'])):
        print('%s not found.' % keywords['detabsfile'])
        halt = True

    if halt:
        return 1

    # Overwrite output flag?
    overwrite = False
    if outfile[0] == '!':
        overwrite = True
        outfile = outfile[1:]

    rmf.make_absrmf(evtfile, outfile,
                rmffile=keywords['rmffile'],
                detabsfile=keywords['detabsfile'],
                overwrite=overwrite)

    return 0


def fitab(args=[]):
    """
    Fit a multi-component background model to spectra from several background
    regions and save the best-fit model to an xcm file. If the intended save
    file exists, will retry 99 times with a number (2 to 100) appended to the
    name.

    Usage:

    fitab bgdinfo.json [savefile=bgdparams.xcm]

    fitab --help  # print a sample bgdinfo.json

    Required in bgdinfo.json:

        bgfiles - An array of spectra file names, extracted from background
            regions, grouped so that bins have gaussian statistics.

        regfiles - An array of region files for the background regions, in the
            same order as bgfiles.

        refimgf - Reference image file for creating region mask images, can be
            the background aperture image file.

        bgdapfiles - Dictionary with 'A' and 'B' keys, pointing to background
            aperture image files for each focal plane module.

        bgddetfiles - Dictionary with 'A' and 'B' keys, pointing to lists of 4
            detector mask image files for each focal plane module.
    """
    if conf.block() is True:
        return 1

    import os
    import json
    import xspec
    import numpy as np
    import astropy.io.fits as pf
    from . import util
    from . import model as numodel

    EXAMPLE_BGDINFO = """
Sample bgdinfo.json:

{
    "bgfiles": [
        "bgd1A_sr_g30.pha", "bgd1B_sr_g30.pha",
        "bgd2A_sr_g30.pha", "bgd2B_sr_g30.pha",
        "bgd3A_sr_g30.pha", "bgd3B_sr_g30.pha"
    ],

    "regfiles": [
        "bgd1A.reg", "bgd1B.reg",
        "bgd2A.reg", "bgd2B.reg",
        "bgd3A.reg", "bgd3B.reg"
    ],

    "refimgf": "bgdapA.fits",

    "bgdapfiles": {
        "A": "bgdapA.fits",
        "B": "bgdapB.fits"
    },

    "bgddetfiles": {
        "A": [
            "det0Aim.fits",
            "det1Aim.fits",
            "det2Aim.fits",
            "det3Aim.fits"
        ],
        "B": [
            "det0Bim.fits",
            "det1Bim.fits",
            "det2Bim.fits",
            "det3Bim.fits"
        ]
    }
}
"""

    if len(args) not in (2, 3):
        print(fitab.__doc__)
        return 0

    if args[1] == '--help':
        print(fitab.__doc__)
        print(EXAMPLE_BGDINFO)
        return 0

    keywords = {
        'savefile': None
    }

    for _ in args[2:]:
        arg = _.split('=')
        if arg[0] in keywords:
            keywords[arg[0]] = arg[1]

    auxildir = conf._AUX_DIR

    # Input params
    bgdinfo = numodel.check_bgdinfofile(args[1])
    if bgdinfo is False:
        print('Error: background info file %s problem.' % args[1])
        return 1

    presets = json.loads(open('%s/ratios.json' % auxildir).read())

    instrlist = numodel.get_keyword_specfiles(bgdinfo['bgfiles'],
        'INSTRUME', ext='SPECTRUM')

    # Compute aperture image and detector mask based weights using each
    # background region's mask
    regmask = util.mask_from_region(bgdinfo['regfiles'],
                                    bgdinfo['refimgf'])
    bgdapim, bgddetim = numodel.load_bgdimgs(bgdinfo)

    # Number of det pixels in the region mask.
    bgddetweights = numodel.calc_det_weights(bgddetim, regmask, instrlist)
    bgddetimsum = bgddetweights['sum']

    # Sum of the aperture image in the region mask.
    bgdapweights = numodel.calc_ap_weights(bgdapim, regmask, instrlist)
    bgdapimwt = bgdapweights['sum']

    refspec = numodel.get_refspec(instrlist)

    # Interact with Xspec
    numodel.addspec_bgd(bgdinfo['bgfiles'])
    numodel.addmodel_apbgd(presets, refspec, bgdapimwt, 2)
    numodel.addmodel_intbgd(presets, refspec, bgddetimsum, 3)
    numodel.addmodel_fcxb(refspec, bgddetimsum, 4)
    numodel.addmodel_intn(presets, refspec, bgddetimsum, 5)
    numodel.run_fit()

    if keywords['savefile'] is None:
        numodel.save_xcm()
    else:
        numodel.save_xcm(prefix=keywords['savefile'].strip())

    return 0


def projobs(args=[]):
    """
    Create an aspect histogram image from pointing info after filtering by GTI.

    nuskybgd projobs aimpoints.fits gtifile=gti.fits out=aspecthist.fits

    Example:

    nuskybgd projobs nu90201039002A_det1.fits out=aspecthistA.fits \\
        gtifile=nu90201039002A01_gti.fits

    nuskybgd projobs nu90201039002B_det1.fits out=aspecthistB.fits \\
        gtifile=nu90201039002B01_gti.fits

    The output file has an image representing the 2D histogram of pointing
    position with time. Gets pointing position from nu%obsid%?_det?.fits and
    good time intervals from nu%obsid%?0?_gti.fits. nu%obsid%?_det?.fits (e.g.
    nu90201039002A_det1.fits) has a table block named 'DET?_REFPOINT', with 3
    columns (TIME, X_DET?, Y_DET?) where ? is the detector number (1-4).
    nu%obsid%?0?_gti.fits (e.g. nu90201039002A01_gti.fits) has a table block
    named 'STDGTI' with two columns (START, STOP) listing intervals of good
    times.

    The image is in an extension with the name ASPECT_HISTOGRAM. Any zero
    padding has been cropped, and the x and y offsets are recorded in the
    header keywords X_OFF and Y_OFF.
    """
    import os
    import astropy.io.fits as pf
    from .util import (
        check_header_aimpoint, check_header_gti, filter_gti
    )
    from .image import (
        make_aspecthist_img, write_aspecthist_img
    )

    if len(args) != 4:
        print(projobs.__doc__)
        return 0

    aimpointfile = args[1]

    keywords = {
        'gtifile': None,
        'out': None
    }

    for _ in args[1:]:
        arg = _.split('=')
        if arg[0] in keywords:
            keywords[arg[0]] = arg[1]

    gtifile = keywords['gtifile']
    outfilename = keywords['out']

    # Check the arguments
    scriptname = os.path.basename(__file__)
    print('Running %s. Performing checks...' % scriptname)

    halt = False

    if not os.path.exists(aimpointfile):
        print('aimpointfile not found: %s' % aimpointfile)
        halt = True

    if gtifile is None:
        print('gtifile= missing')
        halt = True
    elif not os.path.exists(gtifile):
        print('GTI file not found: %s' % gtifile)
        halt = True

    if outfilename is None:
        print('out= missing')
        halt = True
    elif os.path.exists(outfilename) and keywords['out'][0] != '!':
        print('Output file exists: %s' % outfilename)
        halt = True

    if halt:
        print('%s did not complete. See error messages.' % scriptname)
        return 1

    # Check contents of aimpoint and gti files
    aimpointext = None
    detfh = pf.open(aimpointfile)
    for ext in detfh:
        if check_header_aimpoint(ext.header):
            aimpointext = ext
            break
    if aimpointext is None:
        print('No aspect info in the specified file %s.' % aimpointfile)
    else:
        print('Found extension %s.' % aimpointext.header['EXTNAME'])

    gtiext = None
    gtifh = pf.open(gtifile)
    for ext in gtifh:
        if check_header_gti(ext.header):
            gtiext = ext
            break
    if gtiext is None:
        print('No GTI info in the specified file %s.' % gtifile)
    else:
        print('Found extension %s.' % gtiext.header['EXTNAME'])

    # Check output file
    if os.path.exists(outfilename):
        if outfilename[0] == '!':
            outfilename = outfilename[1:]
            print('Overwriting file %s...')
        else:
            print('Output file %s exists (prefix with ! to overwrite)')
            return 1

    coords, dt = filter_gti(aimpointext, gtiext)

    asphistimg, x_min, x_max, y_min, y_max = make_aspecthist_img(coords, dt)

    write_aspecthist_img(
        asphistimg, outfilename, aimpointext,
        (x_min, x_max, y_min, y_max), overwrite=True)

    return 0
