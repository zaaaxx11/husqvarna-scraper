"""GraphQL operations captured from the Husqvarna B2B portal (2026-10-19).

The portal is a SPA; these are the exact queries its own front-end sends, recorded from
the browser and then reproduced server-side with plain HTTP. Nothing here is guessed.

  PRODUCT_QUERY  -> site(name).articles.byIds([id])
                    product + specifications + IPL diagrams + spare parts + related
  PART_QUERY     -> site(name).spareParts.byId(id)
                    one part's detail; callers alias it N times to batch a whole product
"""

SITE = "b2b-us-en-us"

PRODUCT_QUERY = r'''
    query getProductDetailsSections($siteName: String!, $articleId: ID!) {
  site(name: $siteName) {
    articles {
      byIds(ids: [$articleId]) {
        ...ProductDocuments
        ...ProductSpecifications
        ...ProductAccessories
        ...ProductDiamondTools
        ...ProductFeatures
        ...ProductAlsoUsedIn
        ...IplArticle
        ...ProductSpareParts
        ...ProductServiceOffers
      }
    }
  }
}
    fragment ProductServiceOffers on Article {
  professionalOffers: serviceArticleOffers(customerType: COMPANY) {
    ...ServiceOfferArticleFields
  }
  consumerOffers: serviceArticleOffers(customerType: CONSUMER) {
    ...ServiceOfferArticleFields
  }
}
fragment ServiceOfferArticleFields on ServiceArticleOffer {
  servicePnc
  name
  description
  isNew
  contractType
  contractTypeDisplayName
  typeOfService
  availability
  addOnServicePncs
  serviceCanBeCombinedWith
  pricing {
    currency
    duration
    paymentPlanType
    priceExclVat
    priceInclVat
    registrationPriceExclVat
    registrationPriceInclVat
  }
  paymentProviders {
    id
    name
  }
}
fragment ProductDocuments on Article {
  id
  isNew
  isDiscontinued
  name {
    productName
  }
  product {
    category {
      name
    }
    productDocuments {
      url
      fileFormat
      publicationTitle
      publicationType
      languages
    }
  }
}
fragment ProductSpecifications on Article {
  id
  isNew
  isDiscontinued
  articleDescription
  specificationValues {
    id
    formattedValue
  }
  product {
    specifications {
      specificationGroups {
        id
        name
        specifications {
          id
          name
        }
      }
    }
    articles {
      id
      articleDescription
      specificationValues {
        id
        formattedValue
      }
    }
  }
}
fragment ProductAccessories on Article {
  relatedAccessories(skip: 0, take: 50) {
    skip
    take
    totalCount
    result {
      __typename
      id
      articleDescription
      isDiscontinued
      isNew
      name {
        shortName
      }
      mainImage {
        url
        altText
        imageProvider
      }
      product {
        url
        type
        category {
          ...AccessoryCardCategory
        }
        subCategories {
          ...AccessoryCardCategory
        }
      }
    }
  }
}
fragment AccessoryCardCategory on ProductCategory {
  id
  name
  mainHeading
  cardTitle
}
fragment ProductDiamondTools on Article {
  relatedTools {
    ... on DiamondTool {
      __typename
      mainImage {
        url
        altText
        imageProvider
      }
      id
      isNew
      isDiscontinued
      primaryArticle {
        articleNumberFormatted
        articleDescription
        commercialReference
      }
      name {
        shortName
      }
      category {
        name
      }
      url
    }
  }
}
fragment ProductFeatures on Article {
  product {
    sharedFeatures {
      ...ProductDetailsFeature
    }
  }
  additionalFeatures {
    ...ProductDetailsFeature
  }
}
fragment ProductDetailsFeature on Feature {
  id
  name
  description
  video {
    link
    image {
      alt
      sources(configs: [WEBP_SQUARE_COVER_MD, WEBP_SQUARE_COVER_LG]) {
        output
        width
        url
      }
    }
  }
  image {
    url
    altText
  }
}
fragment ProductAlsoUsedIn on Article {
  alsoUsedIn {
    ... on Accessory {
      __typename
      mainImage {
        url
        altText
        imageProvider
      }
      id
      primaryArticle {
        articleNumberFormatted
        commercialReference
      }
      name {
        shortName
      }
      category {
        name
      }
      url
      isDiscontinued
      isNew
    }
    ... on DiamondTool {
      __typename
      mainImage {
        url
        altText
        imageProvider
      }
      id
      primaryArticle {
        articleNumberFormatted
        commercialReference
      }
      name {
        shortName
      }
      category {
        name
      }
      url
      isDiscontinued
      isNew
    }
    ... on Machine {
      __typename
      mainImage {
        url
        altText
        imageProvider
      }
      id
      primaryArticle {
        articleNumberFormatted
        commercialReference
      }
      name {
        shortName
      }
      category {
        name
      }
      url
      isDiscontinued
      isNew
    }
  }
}
fragment IplArticle on Article {
  id
  isNew
  isDiscontinued
  articleDescription
  iplDocuments {
    documentId
    publicationTitle
    url
  }
  ipls {
    ...IplResult
  }
}
fragment IplResult on IPLResult {
  articles {
    ...IplPart
  }
  image
  referenceHeight
  referenceWidth
  name
  id
}
fragment IplPart on IplArticle {
  coordinates
  quantity
  id
  name
  number
  comment
  url
  replacedIds
  commercialReference
  articleDescription
}
fragment ProductSpareParts on Article {
  spareParts {
    ...SparePartsResult
  }
}
fragment SparePartsResult on SparePart {
  id
  name
  description
  articleNumberFormatted
  commercialReference
  mainImage {
    url
    altText
  }
  url
}'''

# The part query, as sent for a single id. Batching wraps the same fragment in aliases:
#   query batch($siteName: String!) { site(name:$siteName){ spareParts {
#       p0: byId(id:"...") { ...sparepart }
#       p1: byId(id:"...") { ...sparepart } } } }
PART_QUERY = r'''
    query getSparePart($siteName: String!, $sparePartId: ID!) {
  site(name: $siteName) {
    spareParts {
      byId(id: $sparePartId) {
        ...sparepart
      }
    }
  }
}
    fragment sparepart on SparePart {
  __typename
  id
  brand
  description
  alsoUsedIn {
    ...AlsoUsedInAccessoryFragment
    ...AlsoUsedInMachineFragment
  }
  articleDescription
  name
  shortName
  articleNumberFormatted
  commercialReference
  mainImage {
    url
    altText
    imageProvider
  }
  specifications {
    grossWeight
    packagingHeight
    packagingLength
    packagingWidth
    ean
    length
    netWeight
    airFilterType
    batteryCellShape
    batteryEnergy
    batteryMaxVoltage
    batteryPackWeight
    batteryRechargeable
    batteryReplaceable
    batteryType
    batteryUsage
    bladeLength
    bladeType
    cellsPerBattery
    diameter
    masterPackQuantity
    nominalCapacity
    nominalVoltage
    packagingType
    power
    ratedCurrent
    useTogetherWithGrassBlades
    useTogetherWithGrassKnifes
    useTogetherWithSawBlades
    articleDescription
  }
  url
}
fragment AlsoUsedInAccessoryFragment on Accessory {
  ... on Accessory {
    __typename
    id
    url
    name {
      longName
      shortName
      productName
    }
    category {
      name
    }
    primaryArticle {
      id
    }
    mainImage {
      url
      altText
      imageProvider
    }
    isDiscontinued
    isNew
  }
}
fragment AlsoUsedInMachineFragment on Machine {
  ... on Machine {
    __typename
    id
    url
    name {
      longName
      shortName
      productName
    }
    category {
      name
    }
    primaryArticle {
      id
    }
    mainImage {
      url
      altText
      imageProvider
    }
    isDiscontinued
    isNew
  }
}'''

# Extra fields the portal fetches in a second call; merged into PART_QUERY so a batched
# request returns specifications AND replacement history together (verified: 20/20 in one
# request, 116 KB response).
REPLACEMENT_HISTORY_FIELDS = "replacementHistory { articleNumber description unformattedArticleNumber }"


# Captured from the portal's own bundle (b2b-browser.js), not guessed.
HERO_QUERY = r'''
    query getProductDetailsHero($siteName: String!, $productId: ID!) {
  site(name: $siteName) {
    products {
      byIds(ids: [$productId]) {
        ...ProductDetailsHero
      }
    }
  }
}
    fragment ProductDetailsHero on Product {
  __typename
  id
  sku
  url
  tagline
  mainImage {
    url
    altText
    imageProvider
  }
  divisionBadge {
    displayName
  }
  specifications {
    topSpecificationDefinitions {
      id
      name
    }
  }
  ... on DiamondTool {
    materials {
      ...Materials
    }
    materialsByRating(includeRatingKeys: OPTIMAL) {
      material
    }
    performanceGradeEnumValue
  }
  articles {
    id
    articleDescription
    listPrice {
      listPriceExcludingVat
      listPriceIncludingVat
      currency
    }
    name {
      productName
    }
    introductionText
    mainImage {
      url
      altText
      imageProvider
    }
    isDiscontinued
    isNew
    specificationValues {
      id
      formattedValue
    }
    repairabilityIndex {
      score
      url
    }
    fitsTo {
      id
      articleDescription
      name {
        shortName
      }
      product {
        id
        name {
          shortName
        }
      }
    }
  }
}
fragment Materials on Materials {
  key
  title
  image {
    sources(configs: [WEBP_SQUARE_COVER_SM]) {
      url
    }
    alt
  }
}'''

CATEGORY_QUERY = r'''
    query productListCategoryProducts($siteId: String!, $categoryId: ID!, $skip: Int!, $take: Int!, $facets: [FacetInput!], $sort: [SortOrderInput!]) {
  site(name: $siteId) {
    productCategories {
      get(productCategoryId: $categoryId) {
        ...ProductListGrid
      }
    }
  }
}
    fragment ProductListGrid on ProductCategory {
  id
  filterProducts(skip: $skip, take: $take, sort: $sort, facets: $facets) {
    skip
    take
    totalCount
    result {
      __typename
      ...ProductGridRow
    }
  }
}
fragment ProductGridRow on Product {
  __typename
  id
  sku
  url
  name {
    longName
  }
  repairabilityIndex {
    score
    url
  }
  divisionBadge {
    displayName
  }
  mainImage {
    url
    altText
    imageProvider
  }
  articles {
    __typename
    id
    numberFormatted
    description {
      shortDescription
    }
    mainImage {
      url
      altText
      imageProvider
    }
    isDiscontinued
    isNew
    repairabilityIndex {
      score
    }
  }
}'''

SEARCH_QUERY = r'''
    query searchForProducts($site: String!, $searchTerm: String!, $brands: [String!], $statuses: [String!], $skip: Int!, $take: Int!) {
  site(name: $site) {
    search {
      content(
        searchTerm: $searchTerm
        showResultsFor: MACHINES
        brands: $brands
        statuses: $statuses
        skip: $skip
        take: $take
      ) {
        results {
          facet {
            ...FacetFields
          }
          facets {
            ...FacetFields
          }
          resultItem {
            __typename
            ...ProductHit
            ...DiamondToolHit
          }
        }
      }
    }
  }
}
    fragment DiamondToolHit on DiamondTool {
  __typename
  id
  sku
  url
  name {
    productName
  }
  mainImage {
    url
    altText
    imageProvider
  }
  selectedArticle
  isDiscontinued
  isNew
  divisionBadge {
    displayName
  }
  category {
    ...ProductCategoryFields
  }
  subCategories {
    ...ProductCategoryFields
  }
  repairabilityIndex {
    score
    url
  }
  primaryArticle {
    id
    isDiscontinued
    isNew
    articleDescription
    commercialReference
    name
    mainImage {
      url
      altText
      imageProvider
    }
  }
}
fragment FacetFields on Facet {
  count
  name
  displayName
  type
}
fragment ProductHit on Machine {
  __typename
  id
  sku
  url
  brand
  name {
    productName
  }
  mainImage {
    url
    altText
    imageProvider
  }
  isAvailable
  isDiscontinued
  isNew
  selectedArticle
  numberOfVariants
  repairabilityIndex {
    score
    url
  }
  divisionBadge {
    displayName
  }
  category {
    ...ProductCategoryFields
  }
  subCategories {
    ...ProductCategoryFields
  }
  primaryArticle {
    id
    isDiscontinued
    isNew
    name
    articleDescription
    commercialReference
    mainImage {
      url
      altText
      imageProvider
    }
  }
}
fragment ProductCategoryFields on ProductCategory {
  id
  name
  mainHeading
  cardTitle
  url
  description
  parentCategory {
    id
  }
}'''
