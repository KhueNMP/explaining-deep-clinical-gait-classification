
'''
@author: Sebastian Lapuschkin
@maintainer: Sebastian Lapuschkin
@contact: sebastian.lapuschkin@hhi.fraunhofer.de
@version: 1.0
@copyright: Copyright (c)  2021, Sebastian Lapuschkin
@license : BSD-2-Clause
'''

# %%
print('importing packages and modules, defining functions...')
import numpy as np
import scipy.io
import time
from termcolor import cprint, colored
import argparse
import os
from natsort import natsorted
import matplotlib.cm

from corelay.processor.base import Processor, Param
from corelay.processor.flow import Sequential, Parallel
from corelay.processor.affinity import SparseKNN
from corelay.pipeline.spectral import SpectralClustering
from corelay.processor.clustering import KMeans
from corelay.processor.embedding import TSNEEmbedding, EigenDecomposition
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt

# custom processors for corelay
class Flatten(Processor):
    def function(self, data):
        return data.reshape(data.shape[0], np.prod(data.shape[1:]))

class Normalize(Processor):
    def function(self, data):
        data = data / data.sum(keepdims=True)
        return data

class TSNEEmbeddingWithPerplexity(TSNEEmbedding):
    perplexity = Param(float, default=30., identifier=True)
    def function(self, data):
        # pylint: disable=not-a-mapping
        tsne = TSNE(n_components=self.n_components, metric=self.metric, perplexity=self.perplexity, **self.kwargs)
        emb = tsne.fit_transform(data)
        return emb

# constants
ANALYSIIS_DATA = ['relevance', 'inputs']
ANALYSIS_GROUPING = ['ground_truth', 'as_predicted', 'all']
ATTRIBUTION_TYPES = ['dom', 'act']
MODELS = ['Cnn1DC8', 'Mlp3Layer768Unit', 'MlpLinear', 'SvmLinearL2C1em1']
FOLDS = [str(f) for f in range(10)] + ['all']
#EMBEDDINGS = ['tsne', 'umap']

# parameterizable data loader
def load_analysis_data(input_root, model, fold, analysis_data, attribution_type, analysis_groups):
    """
        loads and prepares data. for expected input parameters, call script with --help parameter.
        outputs a list of sets of values; each entry in the list is its own input for a SpRAy analysis.
    """
    assert os.path.isdir(input_root), 'Specified project root folder "{}" does not exist!'.format(input_root)
    assert model in MODELS, 'Invalid model argument "{}". Pick from: {}'.format(model, MODELS)
    assert fold in FOLDS, 'Invalid model argument "{}". Pick from: {}'.format(fold, FOLDS)
    assert analysis_data in ANALYSIIS_DATA, 'Invalid model argument "{}". Pick from: {}'.format(analysis_data, ANALYSIIS_DATA)
    assert attribution_type in ATTRIBUTION_TYPES, 'Invalid model argument "{}". Pick from: {}'.format(attribution_type, ATTRIBUTION_TYPES)
    assert analysis_groups in ANALYSIS_GROUPING, 'Invalid analysis_groups argument "{}". Pick from: {}'.format(analysis_groups, ANALYSIS_GROUPING)

    #load precomputed model outputs (predictions, attributions, other jazz)
    targets_health = scipy.io.loadmat('{}/targets.mat'.format(input_root)) # targets.mat in injury type prediction settings with two classes, as per model training
    targets_injurytypes = scipy.io.loadmat('{}/targets_injurytypes.mat'.format(input_root)) # targets.mat in injury type prediction settings with four classes.
    targets_subject = scipy.io.loadmat('{}/subject_labels.mat'.format(input_root))
    input_data = scipy.io.loadmat('{}/data.mat'.format(input_root))
    permutation = scipy.io.loadmat('{}/permutation.mat'.format(input_root))
    splits = scipy.io.loadmat('{}/splits.mat'.format(input_root))


    if fold == 'all':
        fold = [int(f) for f in FOLDS if f != 'all']
    else:
        fold = [int(fold)]

    split_indices = np.concatenate([splits['S'][0,f][0] for f in fold],axis=0)
    y_pred = []; R = []

    for f in fold: # TODO parameterize paths further?
        model_outputs = scipy.io.loadmat('{}/Injury/GRF_AV/{}/part-{}/outputs.mat'.format(input_root, model, f))
        y_pred.append(model_outputs['y_pred'])
        R.append(model_outputs['R_pred_{}_epsilon'.format(attribution_type)])
    y_pred = np.concatenate(y_pred, axis=0)
    R = np.concatenate(R, axis=0)

    true_injury_sublabels = targets_injurytypes['Y'][split_indices]
    true_health_labels = targets_health['Y'][split_indices]
    true_subject_labels = targets_subject['LS'][permutation['P'][0]][split_indices]
    inputs = input_data['X'][split_indices]
    relevances = R

    if analysis_data == 'inputs':
        # do not analyze relevance. we pick the input data instead.
        R = inputs


    if analysis_groups == 'as_predicted':
        y = np.argmax(y_pred, axis=1) # analyze as predicted, y = ypred
    elif analysis_groups == 'ground_truth':
        y = np.argmax(targets_health['Y'][split_indices], axis=1) # analyze as actual label groups stuff, y = ytrue
    else: # 'all'
        y = np.zeros((y_pred.shape[0]), dtype=int) #all classes are the same

    # split data into inputs for multiple experiments, grouped by label assignment strategy for y
    evaluation_groups = []
    for cls in np.unique(y):
        evaluation_groups.append({  'cls':cls,
                                    'y':y[y == cls],
                                    'R':R[y == cls], #misleading naming here, I know. R is the data to be analyzed, may be relevances or inputs
                                    'y_injury_type':true_injury_sublabels[y == cls], # true injury sublabels
                                    'y_health_type':true_health_labels[y == cls], #healthy or not?
                                    'y_subject':true_subject_labels[y==cls], #which guy or gal?
                                    'split_indices':split_indices[y==cls], #which of the (original) data points?
                                    'inputs':inputs[y==cls], # input samples corresponding to the analyzed data
                                    'relevances':relevances[y==cls] # relevance attributions corresponding to the analyzed data
                                    })
    return evaluation_groups


def args_to_stuff(ARGS):
    # reads command line arguments and creates a folder name for figures and info for reproducing the call
    relevant_keys = ['random_seed', 'analysis_data', 'analysis_groups', 'group_index', 'attribution_type',
                    'model', 'fold', 'min_clusters', 'max_clusters',
                    'neighbors_affinity', 'tsne_perplexity', 'cmap_injury', 'cmap_subject', 'cmap_clustering']
    relevant_keys = natsorted(relevant_keys)

    foldername = '-'.join(['{}'.format(getattr(ARGS,k)) for k in relevant_keys])
    args_string = '  '.join(['--{} {}'.format(k, getattr(ARGS,k)) for k in relevant_keys])
    return foldername, args_string


def djordjes_custom_cmap(labels):
    # expects integer type numeric labels in [0,1,2,3,4], where 4 is the aggregate class of gait disorders in [1,2,3]
    # 0: color_normal = [27,158,119]
    # 1: color_ankle = [217,95,2]
    # 2: color_knee = [230,171,2]
    # 3: color_hip = [231,41,138]
    # 4: color_gd = [117,112,179]

    color_normal = [27,158,119]
    color_ankle = [217,95,2]
    color_knee = [230,171,2]
    color_hip = [231,41,138]
    color_gd = [117,112,179]

    ccmap = dict([(i,np.array(v)/255.) for i,v in enumerate([color_normal, color_ankle, color_knee, color_hip, color_gd])])
    return [ccmap[l] for l in labels]


def custom_subject_cmap(labels, cmap):
    # we have ~200 subject labels.
    # this function maps them to a unique consecutive enumeration and then applies a color map to avoid multiple labels bein squashed into
    # the same in in discrete color maps.

    # how many lables do these qualitative matplotlib colormaps support?
    cmap_limits = {'Pastel1':9, 'Pastel2':8, 'Paired':12, 'Accent':8, 'Dark2':8, 'Set1':9, 'Set2':8, 'Set3':12, 'tab10':10, 'tab20':20, 'tab20b':20, 'tab20c':20}
    unique_labels = np.unique(labels)

    enum_map = dict([(l,i) for i,l in enumerate(np.sort(unique_labels))])
    enum_labels = [enum_map[l] for l in labels]

    if cmap in cmap_limits:
        if unique_labels.size > cmap_limits[cmap]:
            cprint(colored('WARNING! You are trying to map {} unique labels using the qualitative color map {}, which only has {} unique values. Picking another color map is advised.'.format(unique_labels.size, cmap, cmap_limits[cmap]), color='yellow'))


    cmap = matplotlib.cm.get_cmap(cmap)
    return([cmap(i/unique_labels.size)[0:3] for i in enum_labels ])




# main module doing most of the things.
def main():

    print('parsing command line arguments...')
    parser = argparse.ArgumentParser(   description="Use Spectral Relevance Analysis via CoReLay to analyze patterns in the model's behavior.",
                                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-rs', '--random_seed', type=str, default='0xDEADBEEF', help='seed for the numpy random generator')
    parser.add_argument('-ag', '--analysis_groups', type=str, default='ground_truth', help='How to handle/group data for analysis. Possible inputs from: {}'.format(ANALYSIS_GROUPING))
    parser.add_argument('-gi', '--group_index', type=str, default='all', help='Among the groups (or classes) of samples in the data, wrt. the grouping specified, via --analysis_groups, which ones to analyze?. Possible inputs from "all" or any valid and positive integer index ')
    parser.add_argument('-ad', '--analysis_data', type=str, default='relevance', help='What to analyze? Relevance attributions, or input data? Possible inputs from: {}'.format(ANALYSIIS_DATA))
    parser.add_argument('-at', '--attribution_type', type=str, default='act', help='Determines the attribution scores wrt either the DOMinant prediction or the ACTual class of a sample. Only valid if data to analyze is relevance. Possible inputs from: {}'.format(ATTRIBUTION_TYPES))
    parser.add_argument('-ir', '--input_root', type=str, default='./data_metaanalysis/2019_frontiers_small_dataset_v3_aff-unaff-atMM_1-234_', help='Root folder of the "input project" to analyze. For now always assumes to be a Injury prediction based on GRV_AV data. This folder should contain all the data and ground truth labels.')
    parser.add_argument('-m', '--model', type=str, default='Cnn1DC8', help='For which model(s precomputed attribution scores) should the analysis be performed? Possible inputs from: {}'.format(MODELS))
    parser.add_argument('-f', '--fold', type=str, default='0', help='Which (test data split/fold should be analyzed? Possible inputs from: {} '.format(FOLDS))
    parser.add_argument('-mc','--min_clusters', type=int, default=3, help='Minimum number of clusters for cluster label assignment in the analysis.' )
    parser.add_argument('-MC','--max_clusters', type=int, default=8, help='Maximum number of clusters for cluster label assignment in the analysis.' )
    parser.add_argument('-na','--neighbors_affinity', type=int, default=3, help='Number of nearest neighbors to consider for affinity graph computation')
    parser.add_argument('-neig', '--number_eigen', type=int, default=8, help='Number of eigenvalues to consider for the spectral embedding, ie, the number of eigenvectors spanning the spectral space, ie, the dimensionalty of the computed spectral embedding')
    parser.add_argument('-tp', '--tsne_perplexity', type=float, default=30., help='The perplexity parameter for the TSNE embedding computation. Lower means more focus on local structures, higher means more focus the global structure.')
    parser.add_argument('-cmapi','--cmap_injury', type=str, default='custom', help='Color map for drawing the ground truth injury labels. Any valid matplotlib colormap name can be given -> OR "custom", which matches the color choices in the remainder of the paper.')
    parser.add_argument('-cmaps','--cmap_subject', type=str, default='viridis', help='Color map for drawing the ground truth subject labels. Any valid matplotlib colormap name can be given')
    parser.add_argument('-cmapc','--cmap_clustering', type=str, default='Set2', help='Color map for drawing the cluster labels inferred by SpRAy. Any valid matplotlib colormap name can be given')
    parser.add_argument('-o', '--output', type=str, default='./output_metaanalysis/2019_frontiers_small_dataset_v3_aff-unaff-atMM_1-234_', help='Output root directory for the computed results. Figures and embedding coordinates, etc, will be stored here in parameter-dependently named sub-folders')
    parser.add_argument('-s','--show', action='store_true', help='Show intermediate figures?')
    parser.add_argument('-sr','--save_results', action='store_true', help='Save results as figures and numpy arrays (e.g. for further processing?)')
    ARGS = parser.parse_args()

    # TODO: plot legend

    print('setting random seed...')
    np.random.seed(int(ARGS.random_seed,0))

    print('loading and preparing data as per specification...')
    evaluation_groups = load_analysis_data(ARGS.input_root, ARGS.model, ARGS.fold, ARGS.analysis_data, ARGS.attribution_type, ARGS.analysis_groups)

    print('Starting Spectral Relevance Analysis...')
    for e in evaluation_groups:
        cls = e['cls']
        if not ARGS.group_index in ['all', str(cls)]:
            print('    skipping group/class {} analysis as per --group_index specification'.format(cls))
            continue

        R = e['R']
        y_true_injury = e['y_injury_type']
        y_true_subject = e['y_subject']
        n_clusters = range(ARGS.min_clusters, ARGS.max_clusters+1) # +1, because range is max value exclusive

        print('    process "{}" relevance for class {} ({}) as per {}'.format(ARGS.attribution_type, cls, ARGS.analysis_groups, ARGS.model))

        pipeline = SpectralClustering(
            #optional, overwrites default settings of SpectralClustering class
            affinity  = SparseKNN(n_neighbors=ARGS.neighbors_affinity, symmetric=True),
            embedding = EigenDecomposition(n_eigval=ARGS.number_eigen),
            clustering=Parallel([
                Parallel([
                    KMeans(n_clusters=k) for k in n_clusters
                ], broadcast=True),
                TSNEEmbeddingWithPerplexity(perplexity=ARGS.tsne_perplexity)
            ], broadcast=True, is_output=True)
        )
        # Data (ie relevance) preprocessors for above pipeline
        pipeline.preprocessing = Sequential([
            Normalize(),    # normnalization to compare the structure in the relevance, not the overall magnitude scaling (which depends on f(x))
            Flatten()       # redundant.
        ])

        start_time = time.perf_counter()

        # Run the pipeline
        # Processors flagged with "is_output=True" will be accumulated in the output
        # the output will be a tree of tuples, with the same hierachy as the pipeline
        # (i.e. clusterings here contains a tuple of the k-means outputs)
        clusterings, tsne_embedding = pipeline(R)

        #center tsne-embedding for visualization
        tsne_embedding -= np.mean(tsne_embedding, axis=0)

        duration = time.perf_counter() - start_time
        print('    Pipeline execution time: {:.4f} seconds with {} input samples'.format(duration, tsne_embedding.shape[0]))

        # drawing figures of results
        fig = plt.figure(figsize=(2*(len(clusterings)+1+1),2.2))


        #true injury sublabel plots
        ax = plt.subplot(1, len(clusterings)+1+1, 1)
        if ARGS.cmap_injury == 'custom':
            print("        drawing true injury labels by picking from djordje's custom colormap for cluster labels")
            ax.scatter( tsne_embedding[:,0],
                        tsne_embedding[:,1],
                        c=djordjes_custom_cmap(np.argmax(y_true_injury,axis=1))
                        )
        else:
            ax.scatter( tsne_embedding[:,0],
                        tsne_embedding[:,1],
                        c=np.argmax(y_true_injury,axis=1),
                        cmap=ARGS.cmap_injury)
        ax.set_ylabel('n={} samples'.format(tsne_embedding.shape[0]))
        ax.set_xlabel('{} GT injury labels'.format(len(np.unique(np.argmax(y_true_injury,axis=1)))))
        ax.set_xticks([])
        ax.set_yticks([])

        #true subject sublabel plots
        ax = plt.subplot(1, len(clusterings)+1+1, 2)
        ax.scatter( tsne_embedding[:,0],
                    tsne_embedding[:,1],
                    c=custom_subject_cmap(np.argmax(y_true_subject,axis=1),ARGS.cmap_subject),
                    )

        ax.set_xlabel('{} GT subject labels'.format(len(np.unique(np.argmax(y_true_subject,axis=1)))))
        ax.set_xticks([])
        ax.set_yticks([])

        #ax.set_aspect('equal')

        for i in range(len(clusterings)):
            ax = plt.subplot(1, len(clusterings)+1+1, i+1+1+1)
            ax.scatter( tsne_embedding[:,0],
                        tsne_embedding[:,1],
                        c=clusterings[i],
                        cmap=ARGS.cmap_clustering)
            ax.set_xlabel('k={} SpRAy clusters'.format(len(np.unique(clusterings[i]))))
            ax.set_xticks([])
            ax.set_yticks([])
            #ax.set_aspect('equal')
            #if i == 0:
            #    ax.set_title('SpRAy clusters ->')

        plt.suptitle('Relevance Clusters; data: {}, model: {}, fold: {}, {} labels: group {}'.format(ARGS.analysis_data if ARGS.analysis_data == 'inputs' else ARGS.analysis_data + ' '  + ARGS.attribution_type,
                                                                                                        ARGS.model, ARGS.fold, ARGS.analysis_groups, cls))
        #plt.tight_layout() # NOTE DO OR DO NOT ?

        if ARGS.save_results:
            if os.path.isfile(ARGS.output):
                print('Can not save results in "{}", exists as FILE already!'.format(ARGS.output))
            else:
                output_dir, args_string = args_to_stuff(ARGS)
                output_dir = '{}/{}'.format(ARGS.output,output_dir)
                #print(output_dir, args_string)

                if not os.path.isdir(output_dir):
                    os.makedirs(output_dir)

                print('    saving figure, args and clusterings/embedding in {}'.format(output_dir))
                plt.savefig('{}/cls-{}.svg'.format(output_dir, cls))
                plt.savefig('{}/cls-{}.pdf'.format(output_dir, cls))
                with open('{}/callparams.args'.format(output_dir), 'wt') as f: f.write(args_string)
                np.save('{}/emb-{}.npy'.format(output_dir, cls), tsne_embedding)
                np.save('{}/clust-{}.npy'.format(output_dir, cls), clusterings)
                np.save('{}/idx-{}.npy'.format(output_dir, cls), e['split_indices'])
                np.save('{}/adata-{}.npy'.format(output_dir, cls), R)
                np.save('{}/inputs-{}.npy'.format(output_dir, cls), e['inputs'])
                np.save('{}/relevances-{}.npy'.format(output_dir, cls), e['relevances'])



    if ARGS.show:
        # show all figures
        plt.show()





#####################
# ENTRY POINT
#####################
if __name__ == '__main__':
    main()

