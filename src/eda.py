#!/usr/bin/env python
"""Exploratory Data Analysis
"""

from lists import REFINED_DIC, CORE_DIC
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.grid_search import GridSearchCV
from sklearn.metrics import make_scorer, mean_squared_error

import json
import luigi
import numpy as np
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def distancesProfile():
    """Explore the distances profile
    """
    ifn = "/work/jaydy/working/PDBbind_refined07-core07.distances.json"
    with open(ifn) as ifs:
        dat = json.loads(ifs.read())

    # minimum distances
    max_dists = []
    min_dists = []
    mean_dists = []
    all_dists = []
    ligand_sizes_4_res = []
    for key, val in dat.iteritems():
        df = pd.DataFrame(val)
        min_dists.extend(df.dists.map(min))
        max_dists.extend(df.dists.map(max))
        mean_dists.extend(df.dists.map(np.mean))
        ligand_sizes_4_res.extend(df.dists.map(
            lambda dists: max(dists) - min(dists)))
        all_dists.extend(df.dists.values.tolist())

    all_dists = [d for l in all_dists for d in l]
    all_dists = pd.Series(all_dists)
    max_dists = pd.Series(max_dists)
    min_dists = pd.Series(min_dists)
    mean_dists = pd.Series(mean_dists)
    lig_sizes = pd.Series(ligand_sizes_4_res)

    plt.figure()
    all_dists.hist(bins=30)
    plt.xlabel("Distances [$\mathrm{\AA}$]")
    plt.savefig("/ddnB/work/jaydy/working/pdbbind/all_dists_hist.tiff")

    print("10% quatile of all distances: {}".format(all_dists.quantile(0.1)))

    plt.figure()
    lig_sizes.hist(bins=20)
    plt.xlabel("Ligand sizes [$\mathrm{\AA}$]")
    plt.savefig("/ddnB/work/jaydy/working/pdbbind/lig_sizes_hist.tiff")

    plt.figure()
    min_dists.hist(bins=30)
    plt.xlabel("Distances [$\mathrm{\AA}$]")
    plt.savefig("/ddnB/work/jaydy/working/pdbbind/min_dists.tiff")

    plt.figure()
    max_dists.hist(bins=30)
    plt.xlabel("Distances [$\mathrm{\AA}$]")
    plt.savefig("/ddnB/work/jaydy/working/pdbbind/max_dists.tiff")

    plt.figure()
    mean_dists.hist(bins=30)
    plt.xlabel("Distances [$\mathrm{\AA}$]")
    plt.savefig("/ddnB/work/jaydy/working/pdbbind/mean_dists.tiff")


class Tokens(luigi.Task):
    binning_size = luigi.Parameter(default=5.0)

    def output(self):
        ofns = [
            "/ddnB/work/jaydy/working/pdbbind/refined.{}.csv".format(
                self.binning_size),
            "/ddnB/work/jaydy/working/pdbbind/core.{}.csv".format(
                self.binning_size)
        ]

        return [luigi.LocalTarget(ofn) for ofn in ofns]

    def run(self):
        ifn = "/work/jaydy/working/PDBbind_refined07-core07.distances.json"
        with open(ifn) as ifs:
            dat = json.loads(ifs.read())

        def getTokens(profiles):
            df = pd.DataFrame(profiles)

            lig_span = df.dists.map(
                lambda dists: max(dists) - min(dists)).mean()

            tokens = []
            for profile in profiles:
                # ignore water molecule or residues too far from the ligand
                if profile["residue"] == "HOH":
                    pass
                elif min(profile["dists"]) > 13.08:
                    tokens.append(profile["residue"])
                else:
                    ends = np.arange(13.08, 13.08 + lig_span,
                                     self.binning_size)
                    type_dists = sorted(
                        zip(profile["atom_types"], profile["dists"]),
                        key=lambda x: x[1])

                    token = profile["residue"]
                    for end in ends:
                        my_type_dists = [
                            t
                            for t in type_dists
                            if t[1] > end and t[1] < (end + self.binning_size)
                        ]
                        if len(my_type_dists) > 0:
                            token = token + "-" + my_type_dists[0][0]
                    tokens.append(token)

            return ' '.join(tokens)

        tokens = [getTokens(p) for p in dat.values()]
        myid_tokens = dict(zip(dat.keys(), tokens))

        refined_dat = [(myid, myid_tokens[myid], REFINED_DIC[myid])
                       for myid in dat.keys() if myid in REFINED_DIC]
        core_dat = [(myid, myid_tokens[myid], CORE_DIC[myid])
                    for myid in dat.keys() if myid in CORE_DIC]

        ofns = [output.path for output in self.output()]
        cols = ['myid', 'tokens', 'ki']
        pd.DataFrame(refined_dat, columns=cols).to_csv(ofns[0])
        pd.DataFrame(core_dat, columns=cols).to_csv(ofns[1])


class RF(luigi.Task):
    """try with the Random Forest algorithm
    """
    binning_size = luigi.Parameter(default=5.0)

    def requires(self):
        return Tokens(binning_size=self.binning_size)

    def run(self):
        task = self.requires()
        if not task.complete():
            raise Exception("{} not completed".format(task))

        refined_ifn, core_ifn = [_.path for _ in task.output()]

        refined_df = pd.read_csv(refined_ifn, index_col=0)
        core_df = pd.read_csv(core_ifn, index_col=0)

        tokens = refined_df.tokens.map(lambda x: x.split()).values
        unique_tokens = set([t for l in tokens for t in l])
        print("{} unique tokens".format(len(unique_tokens)))

        pipe_line = Pipeline(
            [('tfidf', TfidfVectorizer(lowercase=False,
                                       token_pattern=r'(?u)\b\S+\b',
                                       analyzer='word')),
             ('model', RandomForestRegressor(n_estimators=50))])

        grids = {'tfidf__min_df': [0.0], 'tfidf__max_df': [1.0]}

        ki_scorer = make_scorer(mean_squared_error, greater_is_better=False)

        grid_search = GridSearchCV(pipe_line,
                                   grids,
                                   scoring=ki_scorer,
                                   n_jobs=16,
                                   verbose=2,
                                   cv=4)
        grid_search.fit(refined_df['tokens'], refined_df['ki'])

        print("Best score: %0.3f" % grid_search.best_score_)

        print("Best parameters set:")
        best_parameters = grid_search.best_estimator_.get_params()
        for param_name in sorted(grids.keys()):
            print("\t%s: %r" % (param_name, best_parameters[param_name]))

        # predict
        pipe_line = Pipeline([('tfidf', TfidfVectorizer(
            max_df=1.0, min_df=0.1)), ('model', RandomForestRegressor(
                n_estimators=50))])
        pipe_line.fit(refined_df['tokens'], refined_df['ki'])
        prediction = pipe_line.predict(core_df['tokens'])
        score = mean_squared_error(core_df['ki'], prediction)
        print("RMSE on the core set: {}".format(score))

    def output(self):
        pass


def main():
    luigi.build(
        [
            RF(binning_size=7.0), RF(binning_size=6.0), RF(binning_size=5.0),
            RF(binning_size=4.0), RF(binning_size=3.0)
        ],
        local_scheduler=True)


if __name__ == '__main__':
    main()